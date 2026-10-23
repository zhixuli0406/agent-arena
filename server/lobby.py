"""Online lobby: players, matchmaking queues, ready checks, custom rooms, stats.

Follows the matchmaking flow of mainstream online games:
  queue (searching) -> match found (ready_check, timed accept) -> everyone accepts -> match starts (confirmed)
  - Skill rating window: based on player ELO; the accepted rating gap widens linearly with wait time (capped). First queued, first matched; smaller gaps win.
  - Someone declines or times out: that player gets a cooldown and is removed; everyone who accepted keeps their original queue time and goes back first.
  - Custom rooms: the host opens a room, friends join with the room code and each readies up; the host starts once everyone is ready (2+ players).
  - Team queues (2v2, 3v3): queue solo, or form a party first (server/party.py) and the party leader queues; party members always share a side,
    and players on the same network can be teammates but are never made opponents (server/teammatch.py). Parties can't queue for free-for-all.
This module is pure logic (injected clock); the server's background loop calls tick() every second, and the injected start_fn starts matches.
"""

from __future__ import annotations

import bisect
import hashlib
import secrets
import string
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from .i18n import I18nError
from .party import PARTY_SPREAD, Party, PartyMixin
from .teammatch import find_teams, side_possible

BASE_WINDOW = 100.0       # initial accepted ELO gap
WIDEN_PER_SEC = 20.0      # how many points the window widens per second waited
MAX_WINDOW = 800.0
READY_SECONDS = 15.0      # ready check time limit
DECLINE_COOLDOWN = 30.0   # cooldown after declining or timing out
TERMINAL_TTL = 600.0      # how long finished tickets stay queryable
ONLINE_WINDOW = 120.0     # activity within this window counts as online
MAX_PLAYERS = 5000
MAX_SEARCHING = 500       # site-wide cap on players queued at once (keeps the matchmaking loop from being flooded)
MAX_TICKETS_PER_IP = 2    # tickets queued or in ready check at once per IP
GUEST_TTL = 3600.0        # guests with no matches played who are idle longer than this are reaped
RECENT_IPS = 4            # how many recent source IPs to remember per player
NAME_MAX = 24
MODES = ("quiz", "task", "ctf")
SIZES = (2, 3, 4)                     # free-for-all (every player for themselves) sizes
TEAM_FORMATS = {"2v2": 2, "3v3": 3}   # team queues: format -> players per team
FORMATS = ("ffa", *TEAM_FORMATS)
SIDES = ("red", "blue")
ROOM_MAX = 8
ROOM_CODE_LEN = 7
LINK_CODE_LEN = 8         # one-time link code: hands a new credential for the same player to an agent or a browser
LINK_TTL = 600.0
MAX_EXTRA_CREDS = 4       # credentials minted through link codes, newest kept
ROOM_OPEN_TTL = 3600.0    # reap unstarted rooms after this long idle
ROOM_STARTED_TTL = 1800.0 # how long started rooms are kept (so members can still look up token / match_id)
MATCH_BUDGET = 0.05       # max seconds per queue per tick spent matching (runs on the event loop; leftovers wait for the next tick)
ANCHOR_RETRY = 3.0        # a ticket that failed as anchor waits this many seconds before trying again (avoids recomputing doomed combinations every second)


class LobbyError(I18nError):
    """Lobby error: carries a message key and HTTP status code; the API layer translates it to the request language."""


@dataclass
class Player:
    id: str
    name: str
    secret: str                    # plaintext is returned once at join; only the hash is persisted
    secret_hash: str = ""
    rating: float = 1500.0
    agent_label: str = ""          # agent/model name self-reported by the player (for display and the model axis)
    cooldown_until: float = 0.0
    last_seen: float = 0.0
    games: int = 0
    ip: str = ""
    ips: list[str] = field(default_factory=list)   # source IPs of recent requests (for same-network checks; not persisted)
    extra_hashes: list[str] = field(default_factory=list)   # credentials minted through link codes (hashes only)

    def saw_ip(self, ip: str) -> None:
        if ip and ip not in self.ips:
            self.ips = (self.ips + [ip])[-RECENT_IPS:]


@dataclass
class Ticket:
    """A queue ticket. Solo: members = [self]; party: members = the whole party, and player_id is the party leader."""
    id: str
    player_id: str
    mode: str
    size: int                      # total players in the match
    enqueued_at: float
    status: str = "searching"      # searching / ready_check / confirmed / cancelled / declined
    proposal_id: str | None = None
    match_id: str | None = None
    ended_at: float | None = None
    ip: str = ""
    ranked: bool = True
    members: list[str] = field(default_factory=list)
    team_size: int = 0             # 0 = free-for-all; 2/3 = players per team in a team queue
    tokens: dict[str, str] = field(default_factory=dict)
    side: str | None = None        # side assigned in a team match (red / blue)
    retry_at: float = 0.0          # matchmaking backoff: not used as anchor before this time

    def __post_init__(self) -> None:
        if not self.members:
            self.members = [self.player_id]

    @property
    def token(self) -> str | None:
        return self.tokens.get(self.player_id)

    @property
    def fmt(self) -> str:
        return f"{self.team_size}v{self.team_size}" if self.team_size else "ffa"


@dataclass
class Proposal:
    id: str
    mode: str
    size: int
    ticket_ids: list[str]
    deadline: float
    accepted: set[str] = field(default_factory=set)       # ids of players who accepted (every party member must accept)
    sides: dict[str, str] = field(default_factory=dict)   # team match: ticket id -> red / blue


@dataclass
class Room:
    code: str
    host_id: str
    mode: str
    size: int
    members: list[str]
    ready: set[str] = field(default_factory=set)
    status: str = "open"           # open / started
    match_id: str | None = None
    tokens: dict[str, str] = field(default_factory=dict)
    kicked: set[str] = field(default_factory=set)
    touched: float = 0.0           # last time anyone acted (for reaping idle rooms)


# start_fn(mode, players, ranked) -> (match_id, {player_id: token})
StartFn = Callable[..., tuple[str, dict[str, str]]]


class Lobby(PartyMixin):
    def __init__(self, start_fn: StartFn, clock: Callable[[], float] = time.monotonic):
        self._start = start_fn
        self._clock = clock
        self.players: dict[str, Player] = {}
        self.tickets: dict[str, Ticket] = {}
        self.proposals: dict[str, Proposal] = {}
        self.rooms: dict[str, Room] = {}
        self.parties: dict[str, Party] = {}
        self.links: dict[str, tuple[str, float]] = {}   # link code -> (player id, expires at)
        self.wait_samples: list[float] = []
        self.dirty = False              # there are changes to persist

    # ---------------- Players ----------------
    def register(self, name: str, agent_label: str = "", ip: str = "") -> Player:
        if len(self.players) >= MAX_PLAYERS:
            self._reap_guests(force=True)
        if len(self.players) >= MAX_PLAYERS:
            raise LobbyError("lobby_full", 503)
        clean = clean_text(name, NAME_MAX) or "Player"
        secret = secrets.token_urlsafe(18)
        p = Player(id="p_" + secrets.token_hex(5), name=clean, secret=secret, secret_hash=_hash(secret),
                   agent_label=clean_text(agent_label, 40), last_seen=self._clock(), ip=ip)
        p.saw_ip(ip)
        self.players[p.id] = p
        return p

    def auth(self, player_id: str, secret: str, ip: str = "") -> Player:
        p = self.players.get(player_id or "")
        h = _hash(secret or "")
        if p is None:                       # forgotten (a guest that never played, after a restart or reap)
            raise LobbyError("player_unknown", 401)
        if not any(secrets.compare_digest(x, h) for x in [p.secret_hash, *p.extra_hashes]):
            raise LobbyError("auth_failed", 401)        # wrong or revoked credential
        p.last_seen = self._clock()
        p.saw_ip(ip)                       # record on every request: the networks party members actually use count toward same-network checks
        return p

    def public(self, p: Player) -> dict:
        return {"id": p.id, "name": p.name, "rating": round(p.rating), "agent": p.agent_label, "games": p.games}

    def apply_rating(self, player_id: str, delta: float) -> None:
        p = self.players.get(player_id)
        if p is not None:
            p.rating += delta
            p.games += 1
            self.dirty = True

    # ---------------- Matchmaking queues ----------------
    def enqueue(self, player: Player, mode: str, size: int = 2, ip: str = "", fmt: str = "ffa") -> Ticket:
        if mode not in MODES:
            raise LobbyError("bad_mode", mode=mode)
        if fmt not in FORMATS:
            raise LobbyError("bad_format", fmt=fmt)
        party = self.party_of(player.id)
        team_size = TEAM_FORMATS.get(fmt, 0)
        if team_size:
            size = 2 * team_size
            members = list(party.members) if party else [player.id]
            if party and party.leader_id != player.id:
                raise LobbyError("leader_only", 403)
            if len(members) > team_size:
                raise LobbyError("party_too_big", 409, n=team_size)
            ratings = [self.players[m].rating for m in members]
            if max(ratings) - min(ratings) > PARTY_SPREAD:
                raise LobbyError("party_spread", 409, n=int(PARTY_SPREAD))
        else:
            if size not in SIZES:
                raise LobbyError("bad_size", size=size)
            if party and len(party.members) > 1:
                raise LobbyError("party_ffa", 409)   # in free-for-all, teammates would fight each other; parties may only join team queues
            members = [player.id]
        now = self._clock()
        for m in members:
            mp = self.players[m]
            if mp.cooldown_until > now:
                raise LobbyError("cooldown", 429, s=int(mp.cooldown_until - now) + 1)
            if self.active_ticket(m) is not None:
                raise LobbyError("already_queued", 409)
            if self.room_of(m) is not None:
                raise LobbyError("in_room", 409)
        active = [t for t in self.tickets.values() if t.status in ("searching", "ready_check")]
        if len(active) >= MAX_SEARCHING:
            raise LobbyError("queue_full", 503)
        # no limit for loopback (only seen in local development; on the public server Cloudflare supplies the source IP)
        if _net_key(ip) and sum(1 for t in active if t.ip == ip) >= MAX_TICKETS_PER_IP:
            raise LobbyError("ip_tickets", 429, n=MAX_TICKETS_PER_IP)
        t = Ticket(id="t_" + secrets.token_hex(6), player_id=player.id, mode=mode, size=size, enqueued_at=now, ip=ip,
                   members=members, team_size=team_size)
        self.tickets[t.id] = t
        if party:
            party.touched = now
        return t

    def ticket_of(self, player: Player, ticket_id: str) -> Ticket:
        t = self.tickets.get(ticket_id or "")
        if t is None or player.id not in t.members:
            raise LobbyError("ticket_not_found", 404)
        return t

    def cancel(self, ticket: Ticket, player: Player | None = None) -> None:
        """When a party is queued, any member can cancel and the whole party leaves (as in League of Legends)."""
        if ticket.status == "searching":
            self._end(ticket, "cancelled")
        elif ticket.status == "ready_check":
            self.decline(ticket, player)

    def accept(self, ticket: Ticket, player: Player | None = None) -> None:
        prop = self._proposal_of(ticket)
        prop.accepted.add(player.id if player else ticket.player_id)
        if prop.accepted >= set(self._proposal_players(prop)):
            self._launch(prop)

    def decline(self, ticket: Ticket, player: Player | None = None) -> None:
        pid = player.id if player else ticket.player_id
        self._break(self._proposal_of(ticket), losers={ticket.id}, blame={pid})

    def window(self, ticket: Ticket, now: float) -> float:
        return min(BASE_WINDOW + WIDEN_PER_SEC * max(0.0, now - ticket.enqueued_at), MAX_WINDOW)

    def tick(self) -> None:
        now = self._clock()
        for prop in list(self.proposals.values()):          # 1) ready check timeout: anyone who didn't accept counts as declining
            if now >= prop.deadline:
                missing = set(self._proposal_players(prop)) - prop.accepted
                losers = {tid for tid in prop.ticket_ids if set(self.tickets[tid].members) & missing}
                self._break(prop, losers=losers, blame=missing)
        groups: dict[tuple[str, int, int], list[Ticket]] = {}     # 2) form new matches
        for t in self.tickets.values():
            if t.status == "searching":
                groups.setdefault((t.mode, t.size, t.team_size), []).append(t)
        for (mode, size, team_size), pool in groups.items():
            if team_size:
                self._match_team_pool(mode, team_size, pool, now)
            else:
                self._match_pool(mode, size, pool, now)
        for t in list(self.tickets.values()):                # 3) drop expired finished tickets
            if t.ended_at is not None and now - t.ended_at > TERMINAL_TTL:
                self.tickets.pop(t.id, None)
        self._reap_rooms(now)                                # 4) reap idle rooms, parties and guests
        self._reap_parties(now)
        self.links = {c: v for c, v in self.links.items() if v[1] > now}
        self._reap_guests()

    def _match_pool(self, mode: str, size: int, pool: list[Ticket], now: float) -> None:
        """First queued, first matched: each ticket in queue order becomes the anchor; sorting by rating plus binary search limits candidates to the rating window (avoids O(n²))."""
        pool.sort(key=lambda t: t.enqueued_at)
        by_rating = sorted(pool, key=lambda t: self.players[t.player_id].rating)
        keys = [self.players[t.player_id].rating for t in by_rating]
        used: set[str] = set()
        deadline = time.perf_counter() + MATCH_BUDGET
        for anchor in pool:
            if anchor.id in used or anchor.retry_at > now:
                continue
            if time.perf_counter() > deadline:
                break
            ar, aw = self.players[anchor.player_id].rating, self.window(anchor, now)
            lo, hi = bisect.bisect_left(keys, ar - aw), bisect.bisect_right(keys, ar + aw)
            cands = [
                t for t in by_rating[lo:hi]
                if t.id != anchor.id and t.id not in used
                and abs(self.players[t.player_id].rating - ar) <= min(aw, self.window(t, now))
            ]
            cands.sort(key=lambda t: (abs(self.players[t.player_id].rating - ar), t.enqueued_at))
            # Rated matches never pair two tickets from the same network (stops one person farming with two accounts).
            # Loopback is exempt: it only shows up in local development (on the public server Cloudflare supplies the source IP, which can't be spoofed as local).
            # Trade-off: family and friends behind the same NAT can't be matched together; they should use a custom room.
            chosen, ips = [anchor], self._ticket_nets(anchor)
            for t in cands:
                if len(chosen) == size:
                    break
                nets = self._ticket_nets(t)
                if nets & ips:
                    continue
                chosen.append(t)
                ips |= nets
            if len(chosen) < size:
                anchor.retry_at = now + ANCHOR_RETRY
                continue
            self._propose(mode, size, chosen, now)
            used.update(t.id for t in chosen)

    def _match_team_pool(self, mode: str, team_size: int, pool: list[Ticket], now: float) -> None:
        """Team queue: each ticket (solo or full party) is one unit rated at its members' average; first queued, first matched, same rating window as free-for-all."""
        if not side_possible(team_size, {len(t.members) for t in pool}):
            return                                  # e.g. a 3v3 queue with only 2-player parties can never form a full team
        pool.sort(key=lambda t: t.enqueued_at)
        rating = {t.id: self._ticket_rating(t) for t in pool}
        used: set[str] = set()
        deadline = time.perf_counter() + MATCH_BUDGET
        for anchor in pool:
            if anchor.id in used or anchor.retry_at > now:
                continue
            if time.perf_counter() > deadline:
                break
            ar, aw = rating[anchor.id], self.window(anchor, now)
            cands = [t for t in pool if t.id != anchor.id and t.id not in used
                     and abs(rating[t.id] - ar) <= min(aw, self.window(t, now))]
            cands.sort(key=lambda t: (abs(rating[t.id] - ar), t.enqueued_at))
            found = find_teams(anchor, cands, team_size, lambda t: len(t.members),
                               lambda t: rating[t.id], self._ticket_nets)
            if found is None:
                anchor.retry_at = now + ANCHOR_RETRY
                continue
            red, blue = found
            sides = {t.id: "red" for t in red} | {t.id: "blue" for t in blue}
            self._propose(mode, 2 * team_size, [*red, *blue], now, sides)
            used.update(sides)

    def _ticket_rating(self, t: Ticket) -> float:
        return sum(self.players[m].rating for m in t.members) / len(t.members)

    def _ticket_nets(self, t: Ticket) -> set[str]:
        nets = {_net_key(t.ip)}
        for m in t.members:
            p = self.players[m]
            nets |= {_net_key(p.ip)} | {_net_key(x) for x in p.ips}
        return nets - {""}

    def ticket_view(self, t: Ticket, viewer_id: str | None = None) -> dict:
        now = self._clock()
        viewer_id = viewer_id or t.player_id
        view: dict = {"ticket_id": t.id, "status": t.status, "mode": t.mode, "size": t.size, "format": t.fmt,
                      "waited": round(now - t.enqueued_at, 1),
                      "members": [self.public(self.players[m]) for m in t.members if m in self.players]}
        if t.status == "searching":
            view["window"] = round(self.window(t, now))
            view["in_queue"] = sum(len(x.members) for x in self.tickets.values()
                                   if x.status == "searching" and x.mode == t.mode and x.size == t.size
                                   and x.team_size == t.team_size)
            view["avg_wait"] = self.avg_wait()
        elif t.status == "ready_check" and t.proposal_id in self.proposals:
            prop = self.proposals[t.proposal_id]
            players = self._proposal_players(prop)
            side_of = {m: prop.sides.get(tid) for tid in prop.ticket_ids for m in self.tickets[tid].members}
            view["ready"] = {
                "deadline_in": max(0.0, round(prop.deadline - now, 1)),
                "accepted": len(prop.accepted & set(players)),
                "total": len(players),
                "you_accepted": viewer_id in prop.accepted,
                "your_side": prop.sides.get(t.id),
                "players": [{**self.public(self.players[m]), "side": side_of[m]} for m in players],
            }
        elif t.status == "confirmed":
            view["match_id"] = t.match_id
            view["token"] = t.tokens.get(viewer_id)
            view["ranked"] = t.ranked
            view["side"] = t.side
        elif t.status == "declined":
            p = self.players.get(viewer_id) or self.players[t.player_id]   # in a party, only those who didn't accept get the cooldown
            view["cooldown"] = max(0, int(p.cooldown_until - now) + 1)
        return view

    # ---------------- Custom rooms ----------------
    def create_room(self, host: Player, mode: str, size: int = 4) -> Room:
        if mode not in MODES:
            raise LobbyError("bad_mode", mode=mode)
        if self.party_of(host.id) is not None:
            raise LobbyError("in_party", 409)
        if self.active_ticket(host.id) is not None or self.room_of(host.id) is not None:
            raise LobbyError("busy", 409)
        code = self._new_code()
        room = Room(code=code, host_id=host.id, mode=mode, size=max(2, min(int(size), ROOM_MAX)), members=[host.id],
                    touched=self._clock())
        self.rooms[code] = room
        return room

    def room(self, code: str) -> Room:
        r = self.rooms.get((code or "").strip().upper())
        if r is None:
            raise LobbyError("room_not_found", 404)
        r.touched = self._clock()
        return r

    def member_room(self, code: str, player: Player) -> Room:
        """Only members can see room details (the room code isn't secret, but the member list and status are for people in the room)."""
        r = self.room(code)
        if player.id not in r.members:
            raise LobbyError("not_in_room", 403)
        return r

    def join_room(self, code: str, player: Player) -> Room:
        r = self.room(code)
        if player.id in r.members:
            return r
        if r.status != "open":
            raise LobbyError("room_started", 409)
        if player.id in r.kicked:
            raise LobbyError("kicked", 403)
        if len(r.members) >= r.size:
            raise LobbyError("room_full", 409)
        if self.party_of(player.id) is not None:
            raise LobbyError("in_party", 409)
        if self.active_ticket(player.id) is not None or self.room_of(player.id) is not None:
            raise LobbyError("busy", 409)
        r.members.append(player.id)
        return r

    def kick(self, code: str, host: Player, target_id: str) -> Room:
        r = self.room(code)
        if r.host_id != host.id:
            raise LobbyError("host_only_kick", 403)
        if r.status != "open":
            raise LobbyError("room_started", 409)
        if target_id == host.id or target_id not in r.members:
            raise LobbyError("bad_kick", 400)
        r.members.remove(target_id)
        r.ready.discard(target_id)
        r.kicked.add(target_id)                    # a kicked player can't rejoin with the same room code
        return r

    def leave_room(self, code: str, player: Player) -> None:
        r = self.room(code)
        if player.id not in r.members or r.status != "open":
            return
        r.members.remove(player.id)
        r.ready.discard(player.id)
        if not r.members:
            self.rooms.pop(r.code, None)
        elif r.host_id == player.id:
            r.host_id = r.members[0]               # host left: hand over to the earliest member

    def set_ready(self, code: str, player: Player, ready: bool) -> Room:
        r = self.room(code)
        if player.id not in r.members:
            raise LobbyError("not_in_room", 403)
        if r.status != "open":
            raise LobbyError("room_started", 409)
        (r.ready.add if ready else r.ready.discard)(player.id)
        return r

    def start_room(self, code: str, player: Player) -> Room:
        r = self.room(code)
        if r.host_id != player.id:
            raise LobbyError("host_only", 403)
        if r.status != "open":
            raise LobbyError("room_started", 409)
        if len(r.members) < 2:
            raise LobbyError("need_two", 409)
        waiting = [m for m in r.members if m != r.host_id and m not in r.ready]
        if waiting:
            raise LobbyError("not_ready", 409, names=[self.players[m].name for m in waiting])
        # custom rooms don't count on the ladder: friends can restart at will, which would let them farm rating
        match_id, tokens = self._start(r.mode, [self.players[m] for m in r.members], ranked=False)
        r.status, r.match_id, r.tokens = "started", match_id, tokens
        return r

    def room_view(self, r: Room, viewer_id: str | None = None) -> dict:
        view = {
            "code": r.code, "mode": r.mode, "size": r.size, "status": r.status, "match_id": r.match_id,
            "host": r.host_id, "ranked": False,
            "members": [{**self.public(self.players[m]), "ready": m in r.ready or m == r.host_id,
                         "host": m == r.host_id} for m in r.members],
        }
        if viewer_id and viewer_id in r.tokens:
            view["token"] = r.tokens[viewer_id]     # connection token goes only to its owner
        return view

    # ---------------- Stats ----------------
    def avg_wait(self) -> float | None:
        return round(sum(self.wait_samples) / len(self.wait_samples), 1) if self.wait_samples else None

    def stats(self) -> dict:
        now = self._clock()
        queues: dict[str, int] = {}
        for t in self.tickets.values():
            if t.status == "searching":
                key = f"{t.mode}:{t.fmt if t.team_size else t.size}"
                queues[key] = queues.get(key, 0) + len(t.members)
        return {
            "parties": len(self.parties),
            "online": sum(1 for p in self.players.values() if now - p.last_seen < ONLINE_WINDOW),
            "queues": queues,
            "searching": sum(queues.values()),
            "rooms_open": sum(1 for r in self.rooms.values() if r.status == "open"),
            "avg_wait": self.avg_wait(),
        }

    # ---------------- Internals ----------------
    def active_ticket(self, player_id: str) -> Ticket | None:
        for t in self.tickets.values():
            if player_id in t.members and t.status in ("searching", "ready_check"):
                return t
        return None

    def room_of(self, player_id: str) -> Room | None:
        for r in self.rooms.values():
            if r.status == "open" and player_id in r.members:
                return r
        return None

    def _proposal_of(self, ticket: Ticket) -> Proposal:
        prop = self.proposals.get(ticket.proposal_id or "")
        if ticket.status != "ready_check" or prop is None:
            raise LobbyError("no_pending", 409)
        return prop

    def _end_party_ticket(self, party: Party) -> None:
        """Party membership changed: void the party's queue ticket (no cooldown; if in ready check, the others go back to the queue first)."""
        t = self.active_ticket(party.leader_id)
        if t is None or len(t.members) < 2:
            return
        if t.status == "searching":
            self._end(t, "cancelled")
        elif t.status == "ready_check" and t.proposal_id in self.proposals:
            self._break(self.proposals[t.proposal_id], losers={t.id}, blame=set())

    def _proposal_players(self, prop: Proposal) -> list[str]:
        return [m for tid in prop.ticket_ids for m in self.tickets[tid].members]

    def _propose(self, mode: str, size: int, chosen: list[Ticket], now: float,
                 sides: dict[str, str] | None = None) -> None:
        prop = Proposal(id="m_" + secrets.token_hex(5), mode=mode, size=size,
                        ticket_ids=[t.id for t in chosen], deadline=now + READY_SECONDS, sides=sides or {})
        self.proposals[prop.id] = prop
        for t in chosen:
            t.status, t.proposal_id = "ready_check", prop.id

    def _break(self, prop: Proposal, losers: set[str], blame: set[str] | None = None) -> None:
        """losers: tickets to remove from the queue (a party is out if any member didn't accept); blame: players to put on cooldown (those who didn't accept)."""
        now = self._clock()
        for tid in prop.ticket_ids:
            t = self.tickets[tid]
            t.proposal_id = None
            if tid in losers:
                for m in t.members:
                    if blame is None or m in blame:
                        self.players[m].cooldown_until = now + DECLINE_COOLDOWN
                self._end(t, "declined")
            else:
                t.status = "searching"             # keep enqueued_at: back to the front of the queue
        self.proposals.pop(prop.id, None)

    def _launch(self, prop: Proposal) -> None:
        players = [self.players[m] for m in self._proposal_players(prop)]
        if prop.sides:
            sides = {m: prop.sides[tid] for tid in prop.ticket_ids for m in self.tickets[tid].members}
            match_id, tokens = self._start(prop.mode, players, ranked=True, teams=sides)
        else:
            match_id, tokens = self._start(prop.mode, players, ranked=True)
        now = self._clock()
        for tid in prop.ticket_ids:
            t = self.tickets[tid]
            t.match_id, t.side = match_id, prop.sides.get(tid)
            t.tokens = {m: tokens[m] for m in t.members if m in tokens}
            self.wait_samples.append(now - t.enqueued_at)
            self._end(t, "confirmed")
        self.wait_samples = self.wait_samples[-100:]
        self.proposals.pop(prop.id, None)

    def _end(self, t: Ticket, status: str) -> None:
        t.status, t.ended_at = status, self._clock()

    # ---------------- Link codes (website <-> agent, same player) ----------------
    def create_link(self, player: Player) -> tuple[str, float]:
        """A one-time, short-lived code. Whoever redeems it gets a NEW credential for this player, so an agent
        never needs the browser's secret (and the browser never needs the agent's)."""
        now = self._clock()
        self.links = {c: v for c, v in self.links.items() if v[0] != player.id and v[1] > now}
        alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(LINK_CODE_LEN))
            if code not in self.links:
                break
        self.links[code] = (player.id, now + LINK_TTL)
        return code, LINK_TTL

    def redeem_link(self, code: str) -> tuple[Player, str]:
        entry = self.links.pop((code or "").strip().upper(), None)
        now = self._clock()
        if entry is None or entry[1] <= now or entry[0] not in self.players:
            raise LobbyError("link_invalid", 404)
        p = self.players[entry[0]]
        secret = secrets.token_urlsafe(18)
        p.extra_hashes = (p.extra_hashes + [_hash(secret)])[-MAX_EXTRA_CREDS:]
        p.last_seen = now
        self.dirty = True
        return p, secret

    def has_credential(self, player_id: str, secret_hash: str) -> bool:
        p = self.players.get(player_id)
        return p is not None and any(secrets.compare_digest(x, secret_hash) for x in [p.secret_hash, *p.extra_hashes])

    def reset_credentials(self, player: Player, secret: str) -> None:
        """Keep only the credential making this call: every other browser and linked agent is signed out,
        and unused link codes die. The way to recover from a leaked secret or link."""
        player.secret_hash, player.extra_hashes = _hash(secret), []
        self.links = {c: v for c, v in self.links.items() if v[0] != player.id}
        self.dirty = True

    # ---------------- Persistence ----------------
    def dump(self) -> dict:
        """Only players who have played a match are saved; secrets are stored as hashes only (backups go to the public repo's data branch)."""
        return {"version": 1, "players": [
            {"id": p.id, "name": p.name, "rating": round(p.rating, 2), "games": p.games,
             "agent": p.agent_label, "secret_hash": p.secret_hash, "extra_hashes": list(p.extra_hashes)}
            for p in self.players.values() if p.games > 0]}

    def restore(self, data: dict) -> int:
        n = 0
        for d in (data or {}).get("players", [])[:MAX_PLAYERS]:
            pid, h = str(d.get("id", "")), str(d.get("secret_hash", ""))
            if not pid.startswith("p_") or len(h) != 64 or pid in self.players:
                continue
            try:
                rating, games = float(d.get("rating", 1500.0)), int(d.get("games", 0))
            except (TypeError, ValueError):
                continue
            extra = [x for x in (d.get("extra_hashes") or []) if isinstance(x, str) and len(x) == 64][-MAX_EXTRA_CREDS:]
            self.players[pid] = Player(
                id=pid, name=clean_text(str(d.get("name", "")), NAME_MAX) or "Player", secret="", secret_hash=h,
                rating=rating, agent_label=clean_text(str(d.get("agent", "")), 40), games=games, extra_hashes=extra)
            n += 1
        return n

    def _reap_rooms(self, now: float) -> None:
        for code, r in list(self.rooms.items()):
            ttl = ROOM_OPEN_TTL if r.status == "open" else ROOM_STARTED_TTL
            if now - r.touched > ttl:
                self.rooms.pop(code, None)

    def _reap_guests(self, force: bool = False) -> None:
        """Reap guests who have never played, have been idle too long, and aren't in a queue or room (stops sign-up floods from filling capacity).
        force (capacity full): ignore the idle threshold and clear a batch of the longest-idle guests,
        so new players can always get in even if someone floods sign-ups from many IPs (the flood accounts push each other out).
        If flood accounts form parties or open rooms to hold spots, then when capacity is full, parties and rooms that aren't queued
        and whose members all have zero matches are also disbanded in a batch (longest idle first)."""
        now = self._clock()
        if force:
            self._disband_guest_groups(max(1, MAX_PLAYERS // 100))
        busy = {m for t in self.tickets.values() if t.status in ("searching", "ready_check") for m in t.members}
        for r in self.rooms.values():
            busy.update(r.members)
        for party in self.parties.values():
            busy.update(party.members)
        idle = [p for pid, p in self.players.items() if p.games == 0 and pid not in busy]
        if force:
            # flood accounts come from a few IPs: evict guests from the most crowded IPs first, oldest first
            per_ip: dict[str, int] = {}
            for p in idle:
                per_ip[p.ip] = per_ip.get(p.ip, 0) + 1
            idle.sort(key=lambda p: (-per_ip.get(p.ip, 0), p.last_seen))
            for p in idle[: max(1, MAX_PLAYERS // 100)]:
                self.players.pop(p.id, None)
            return
        for p in idle:
            if now - p.last_seen > GUEST_TTL:
                self.players.pop(p.id, None)

    def _disband_guest_groups(self, limit: int) -> None:
        def guests_only(members: list[str]) -> bool:
            return all(self.players[m].games == 0 for m in members if m in self.players)
        parties = sorted((p for p in self.parties.values()
                          if self.active_ticket(p.leader_id) is None and guests_only(p.members)),
                         key=lambda p: p.touched)
        for p in parties[:limit]:
            self.parties.pop(p.code, None)
        rooms = sorted((r for r in self.rooms.values() if r.status == "open" and guests_only(r.members)),
                       key=lambda r: r.touched)
        for r in rooms[:limit]:
            self.rooms.pop(r.code, None)

    def _new_code(self) -> str:
        alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"  # drop the easily confused O/I/0/1
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(ROOM_CODE_LEN))
            if code not in self.rooms and code not in self.parties:
                return code


def _net_key(ip: str) -> str:
    """Key for same-network checks: empty string = no restriction (unknown source or loopback)."""
    if not ip or ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127."):
        return ""
    return ip


def clean_text(value: str, limit: int) -> str:
    """Player-visible text: strip control/format characters (including bidi overrides), collapse whitespace, truncate."""
    s = "".join(" " if ch.isspace() else ch for ch in str(value or "") if ch.isspace() or unicodedata.category(ch)[0] != "C")
    return " ".join(s.split())[:limit]


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
