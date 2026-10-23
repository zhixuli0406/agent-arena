"""Parties: friends form a party, then the party leader queues them together in the team queue; matchmaking always keeps them on the same side.

Modeled on League of Legends: party size is capped by the queue (2v2 up to 2, 3v3 up to 3), parties have a max rating spread,
and if anyone leaves, the whole party leaves the queue. Parties live in memory only (a server restart disbands them; just regroup).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .i18n import I18nError

PARTY_MAX = 3            # largest team queue is 3v3
PARTY_SPREAD = 300.0     # max gap between the highest and lowest member rating (stops high-rated players boosting low-rated ones)
PARTY_IDLE_TTL = 3600.0  # disband after this long idle and not queued


@dataclass
class Party:
    code: str
    leader_id: str
    members: list[str]
    kicked: set[str] = field(default_factory=set)
    touched: float = 0.0


class PartyMixin:
    """Mixin for Lobby: needs self.players, self.parties, self._clock, self._new_code,
    self.active_ticket, self.room_of, self._end_party_ticket."""

    def create_party(self, player) -> Party:
        self._ensure_free(player.id)
        party = Party(code=self._new_code(), leader_id=player.id, members=[player.id], touched=self._clock())
        self.parties[party.code] = party
        return party

    def party(self, code: str) -> Party:
        p = self.parties.get((code or "").strip().upper())
        if p is None:
            raise I18nError("party_not_found", 404)
        return p

    def member_party(self, code: str, player) -> Party:
        p = self.party(code)
        if player.id not in p.members:
            raise I18nError("not_in_party", 403)
        p.touched = self._clock()
        return p

    def party_of(self, player_id: str) -> Party | None:
        for p in self.parties.values():
            if player_id in p.members:
                return p
        return None

    def join_party(self, code: str, player) -> Party:
        p = self.party(code)
        if player.id in p.members:
            return p
        if player.id in p.kicked:
            raise I18nError("party_kicked", 403)
        if len(p.members) >= PARTY_MAX:
            raise I18nError("party_full", 409, n=PARTY_MAX)
        if self.active_ticket(p.leader_id) is not None:
            raise I18nError("party_queued", 409)
        self._ensure_free(player.id)
        ratings = [self.players[m].rating for m in p.members] + [player.rating]
        if max(ratings) - min(ratings) > PARTY_SPREAD:
            raise I18nError("party_spread", 409, n=int(PARTY_SPREAD))
        p.members.append(player.id)
        p.touched = self._clock()
        return p

    def leave_party(self, player) -> None:
        p = self.party_of(player.id)
        if p is None:
            return
        self._no_dodge(p)
        self._end_party_ticket(p)          # someone left: the whole party leaves the queue (as in League of Legends)
        p.members.remove(player.id)
        if not p.members:
            self.parties.pop(p.code, None)
        elif p.leader_id == player.id:
            p.leader_id = p.members[0]

    def kick_from_party(self, leader, target_id: str) -> Party:
        p = self.party_of(leader.id)
        if p is None:
            raise I18nError("not_in_party", 403)
        if p.leader_id != leader.id:
            raise I18nError("leader_only", 403)
        if target_id == leader.id or target_id not in p.members:
            raise I18nError("bad_kick", 400)
        self._no_dodge(p)
        self._end_party_ticket(p)
        p.members.remove(target_id)
        p.kicked.add(target_id)
        return p

    def party_view(self, p: Party, viewer_id: str | None = None) -> dict:
        t = self.active_ticket(p.leader_id)
        return {
            "code": p.code, "leader": p.leader_id, "max": PARTY_MAX,
            "members": [{**self.public(self.players[m]), "leader": m == p.leader_id} for m in p.members],
            "queued": bool(t and t.members == p.members),
            "ticket_id": t.id if t and viewer_id in t.members else None,
        }

    def _no_dodge(self, p: Party) -> None:
        """No leaving or kicking during a ready check: otherwise a party could see the opponents, bail for free and requeue (picking opponents to farm rating).
        If you really don't want to play, decline; the cooldown lands on whoever declined."""
        t = self.active_ticket(p.leader_id)
        if t is not None and t.status == "ready_check":
            raise I18nError("party_in_check", 409)

    def _ensure_free(self, player_id: str) -> None:
        if self.party_of(player_id) is not None:
            raise I18nError("in_party", 409)
        if self.active_ticket(player_id) is not None or self.room_of(player_id) is not None:
            raise I18nError("busy", 409)

    def _reap_parties(self, now: float) -> None:
        for code, p in list(self.parties.items()):
            p.members = [m for m in p.members if m in self.players]
            if not p.members:
                self.parties.pop(code, None)
                continue
            if p.leader_id not in p.members:
                p.leader_id = p.members[0]
            if self.active_ticket(p.leader_id) is None and now - p.touched > PARTY_IDLE_TTL:
                self.parties.pop(code, None)
