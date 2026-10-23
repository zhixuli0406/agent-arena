"""Shared server state: match registry, match start, public safety policy, lobby instance, ladder rating write-back.

Public policy: the public server only accepts player-brought agents (remote) and demo agents (mock),
and never plays for anyone with the server owner's model logins or keys. For local personal use, set ARENA_ALLOW_HOST_ADAPTERS=1 to lift this.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from itertools import combinations
from typing import Any, Callable

from arena.adapters.remote import drop_slot, get_slot
from arena.elo import Ratings
from arena.engine import MatchReport, run_match
from arena.types import AgentSpec, MatchConfig

from .agents import AgentHub
from .i18n import I18nError
from .lobby import Lobby, Player
from .question_bank import PUBLIC_CTF_CONFIG, pick
from .spectate import public_faults

log = logging.getLogger("arena.server")

RUNS_DIR = os.environ.get("ARENA_RUNS_DIR", "runs")
LADDER_PATH = os.environ.get("ARENA_LADDER", os.path.join(RUNS_DIR, "ladder.json"))
STATE_PATH = os.environ.get("ARENA_STATE", os.path.join(RUNS_DIR, "lobby_state.json"))
PUBLIC_ADAPTERS = {"remote", "mock"}
ALLOW_HOST_ADAPTERS = os.environ.get("ARENA_ALLOW_HOST_ADAPTERS") == "1"
MAX_LIVE_MATCHES = int(os.environ.get("ARENA_MAX_LIVE", "50"))
MAX_LIVE_DEMOS = 5        # demo matches (mock vs mock) have their own quota so they can't take slots from real matches
SLOT_TTL = 600  # how long to keep a connection slot after a match ends (so player clients receive the end signal)
MATCH_TTL = 3600.0        # how long finished match summaries stay in memory
TRANSCRIPT_TTL = 86400.0  # how long transcript files are kept
LOBBY_STEP_TIMEOUT = 120  # per-question time limit for lobby matches (seconds)
DAILY_PAIR_CAP = 3        # max matches per day between the same opponents that count on the ladder (stops two accounts farming each other)
MATCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")

matches: dict[str, dict[str, Any]] = {}
valid_tokens: set[str] = set()


PUBLIC_MODES = {"quiz", "task", "ctf"}
PUBLIC_CTF_MAX_ROUNDS = 12
PUBLIC_CTF_STEP_TIMEOUT = 120
PUBLIC_CTF_WALL_SECONDS = 300
MAX_MATCH_AGENTS = 8
MAX_MATCH_ITEMS = 20


class PolicyError(I18nError):
    """Public policy violation: always 403."""

    def __init__(self, key: str, **params: object):
        super().__init__(key, 403, **params)


def check_public(cfg: MatchConfig) -> None:
    """Public server match policy: only player-brought and demo agents, only modes that need no local resources, and a cap on match size."""
    if ALLOW_HOST_ADAPTERS:
        return
    bad = sorted({a.adapter for a in cfg.agents if a.adapter not in PUBLIC_ADAPTERS})
    if bad:
        raise PolicyError("policy_adapters", bad=bad)
    if cfg.mode not in PUBLIC_MODES:
        raise PolicyError("policy_mode", mode=cfg.mode)
    if cfg.mode == "ctf":
        runtime_limits = (cfg.max_rounds, cfg.timeout_seconds, cfg.max_wall_seconds)
        required_limits = (PUBLIC_CTF_MAX_ROUNDS, PUBLIC_CTF_STEP_TIMEOUT, PUBLIC_CTF_WALL_SECONDS)
        if cfg.mode_config != PUBLIC_CTF_CONFIG or runtime_limits != required_limits:
            raise PolicyError("policy_ctf")
    if len(cfg.agents) > MAX_MATCH_AGENTS:
        raise PolicyError("max_agents", n=MAX_MATCH_AGENTS)
    items = cfg.mode_config.get("tasks" if cfg.mode == "task" else "questions") or []
    if len(items) > MAX_MATCH_ITEMS:
        raise PolicyError("max_items", n=MAX_MATCH_ITEMS)
    # long limits would let one match hold a live slot for hours
    if cfg.timeout_seconds > LOBBY_STEP_TIMEOUT or cfg.max_wall_seconds > MAX_MATCH_ITEMS * LOBBY_STEP_TIMEOUT + 300:
        raise PolicyError("bad_limits")


def live_count(source: str | None = None) -> int:
    return sum(1 for m in matches.values()
               if not m["task"].done() and (source is None or m.get("source") == source))


def start_match(cfg: MatchConfig, on_done: Callable[[MatchReport], None] | None = None,
                meta: dict[str, Any] | None = None) -> str:
    check_public(cfg)                          # defense in depth: every match on a public server obeys the policy
    if live_count() >= MAX_LIVE_MATCHES:
        raise I18nError("server_busy", 503)
    match_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    tokens = [s.params["token"] for s in cfg.agents if s.adapter == "remote" and s.params.get("token")]
    for tok in tokens:
        valid_tokens.add(tok)
        get_slot(tok)
    task = asyncio.create_task(run_match(cfg, runs_dir=RUNS_DIR, match_id=match_id))

    def _done(t: asyncio.Task) -> None:
        for tok in tokens:
            get_slot(tok).finish()                      # broadcast: match over (visible to every connection)
        loop = asyncio.get_running_loop()
        loop.call_later(SLOT_TTL, _cleanup, tokens)
        if t.cancelled():
            return
        if t.exception() is not None:
            log.error("match %s crashed: %r", match_id, t.exception())   # details go to the server log only, never to the caller
            return
        if on_done is not None:
            try:
                on_done(t.result())
            except Exception:  # noqa: BLE001 — a failed write-back doesn't affect the match itself, but log it
                log.exception("match %s on_done failed", match_id)

    task.add_done_callback(_done)
    matches[match_id] = {"task": task, "mode": cfg.mode, "players": [s.id for s in cfg.agents],
                         "started": time.time(), **(meta or {})}
    sides = {s.id: s.team for s in cfg.agents if s.team}
    if sides:
        matches[match_id]["sides"] = sides                # team match: who is on which side (for spectator coloring)
    return match_id


def live_match_of(player_id: str) -> str | None:
    """The lobby match this player is seated in right now, if any."""
    for mid, m in matches.items():
        if player_id in m.get("pids", ()) and not m["task"].done():
            return mid
    return None


def _cleanup(tokens: list[str]) -> None:
    for tok in tokens:
        drop_slot(tok)
        valid_tokens.discard(tok)


def reap(now: float | None = None) -> None:
    """Reap match summaries finished more than MATCH_TTL ago and transcript files older than TRANSCRIPT_TTL. Called periodically by the background loop."""
    now = time.time() if now is None else now
    for mid, m in list(matches.items()):
        if m["task"].done() and now - m["started"] > MATCH_TTL:
            matches.pop(mid, None)
    try:
        names = os.listdir(RUNS_DIR)
    except FileNotFoundError:
        return
    for name in names:
        if not name.endswith(".jsonl") or not MATCH_ID_RE.match(name[:-6]):
            continue
        path = os.path.join(RUNS_DIR, name)
        try:
            if now - os.path.getmtime(path) > TRANSCRIPT_TTL:
                os.remove(path)
        except OSError:
            log.warning("reap transcript failed: %s", path)


def match_summary(match_id: str) -> dict[str, Any]:
    m = matches[match_id]
    task: asyncio.Task = m["task"]
    out: dict[str, Any] = {"match_id": match_id, "mode": m["mode"], "players": m["players"],
                           "started": m["started"], "source": m.get("source", "api")}
    if m.get("sides"):
        out["sides"] = m["sides"]
    if not task.done():
        out["status"] = "RUNNING"
    elif task.cancelled() or task.exception() is not None:
        out["status"] = "ERROR"
    else:
        rep = task.result()
        out["status"] = rep.status
        if rep.result:
            out["ranking"] = rep.result.ranking
            out["scores"] = rep.result.scores
            if "team_ranking" in rep.result.details:
                out["team_ranking"] = rep.result.details["team_ranking"]
                out["team_scores"] = rep.result.details["team_scores"]
                out["teams"] = rep.result.details["teams"]
        out["rated"] = rep.rated
        out["forfeits"] = public_faults(m["mode"], rep.forfeits)
    return out


def recent_matches(limit: int = 30) -> list[dict[str, Any]]:
    ids = sorted(matches, key=lambda k: matches[k]["started"], reverse=True)[:limit]
    return [match_summary(i) for i in ids]


# ---------------- Demo match: mock vs mock, fixed settings, separate quota ----------------
def start_demo() -> str:
    if live_count("demo") >= MAX_LIVE_DEMOS:
        raise I18nError("demo_busy", 503)
    mode_config = pick("quiz", n=5)
    truth = [q["answer"][0] if isinstance(q["answer"], list) else q["answer"] for q in mode_config["questions"]]
    cfg = MatchConfig.from_dict({
        "mode": "quiz", "mode_config": mode_config, "ratings_path": "",
        "agents": [   # two scripted agents: A gets four right, B gets three, so viewers see a clear winner
            {"id": "Demo-A", "adapter": "mock", "model": "mock",
             "params": {"answers": [a if i != 3 else "?" for i, a in enumerate(truth)], "delay": 0.8}},
            {"id": "Demo-B", "adapter": "mock", "model": "mock",
             "params": {"answers": [a if i % 2 == 0 else "?" for i, a in enumerate(truth)], "delay": 1.1}},
        ],
        "timeout_seconds": 10, "max_wall_seconds": 120,
    })
    return start_match(cfg, meta={"source": "demo"})


# ---------------- Ladder anti-farming: daily rated-match cap per opponent pair ----------------
_pair_counts: dict[tuple[str, frozenset[str]], int] = {}


def _ranked_today(player_ids: list[str], teams: dict[str, str] | None = None) -> bool:
    """Any two opponents get only their first DAILY_PAIR_CAP matches per day (UTC) counted on the ladder; if any pair is over, the whole match is unrated.
    Counted per opponent pair (in team matches, only across sides), so bringing in a stranger to fill the match doesn't get around it."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    for k in [k for k in _pair_counts if k[0] != day]:
        _pair_counts.pop(k, None)
    ok = True
    for a, b in combinations(player_ids, 2):
        if teams and teams.get(a) == teams.get(b):
            continue                                   # teammates playing together is normal; no cap
        key = (day, frozenset((a, b)))
        _pair_counts[key] = _pair_counts.get(key, 0) + 1
        ok = ok and _pair_counts[key] <= DAILY_PAIR_CAP
    return ok


# ---------------- Lobby match start: one connection slot per player ----------------
def _lobby_start(mode: str, players: list[Player], ranked: bool = True,
                 teams: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """teams = {player_id: red/blue}: a team match. The winner is decided by team total score; individual ratings are compared only against the opposing team (arena/elo.py)."""
    ranked = ranked and _ranked_today([p.id for p in players], teams)
    tokens: dict[str, str] = {}
    agents: list[dict[str, Any]] = []
    agent_to_player: dict[str, str] = {}
    used: set[str] = set()
    for p in players:
        tok = secrets.token_urlsafe(12)
        tokens[p.id] = tok
        aid, n = p.name, 2
        while aid in used:
            aid, n = f"{p.name}#{n}", n + 1
        used.add(aid)
        agent_to_player[aid] = p.id
        agents.append({"id": aid, "adapter": "remote", "model": p.agent_label or "self-hosted",
                       "prompt_author": p.id, "params": {"token": tok}, "team": (teams or {}).get(p.id, "")})
    mode_config = pick(mode)
    items = mode_config.get("questions") or mode_config.get("tasks") or []
    is_ctf = mode == "ctf"
    cfg = MatchConfig.from_dict({
        "mode": mode, "mode_config": mode_config, "agents": agents,
        "ratings_path": LADDER_PATH if ranked else "",          # unrated matches never touch the ladder file
        "team_ladder": False,                                    # red/blue are random teams; no team ladder
        "max_rounds": PUBLIC_CTF_MAX_ROUNDS if is_ctf else 100,
        "timeout_seconds": PUBLIC_CTF_STEP_TIMEOUT if is_ctf else LOBBY_STEP_TIMEOUT,
        # the wall-clock cap must exceed (questions x per-question limit), or a losing player could stall every question to make the match DEGRADED and unrated
        "max_wall_seconds": PUBLIC_CTF_WALL_SECONDS if is_ctf else len(items) * LOBBY_STEP_TIMEOUT + 300,
    })

    def _ladder(rep: MatchReport) -> None:
        if not ranked:
            return
        for aid, pid in agent_to_player.items():
            lobby.apply_rating(pid, rep.elo_deltas.get(aid, {}).get("prompt", 0.0))

    mid = start_match(cfg, on_done=_ladder, meta={"source": "lobby", "ranked": ranked, "pids": [p.id for p in players]})
    for p in players:                         # the seat token goes to the player's agent, never to the lobby page
        hub.assign(p.id, {"match_id": mid, "token": tokens[p.id], "mode": mode, "ranked": ranked,
                             "side": (teams or {}).get(p.id)})
    return mid, tokens


lobby = Lobby(_lobby_start)
hub = AgentHub()          # agent standby channels: presence + seat dispatch


def leaderboard(limit: int = 20) -> dict[str, Any]:
    data = Ratings(LADDER_PATH).data
    models = sorted(data.get("model", {}).items(), key=lambda kv: -kv[1])[:limit]
    players = sorted(data.get("prompt", {}).items(), key=lambda kv: -kv[1])[:limit]

    def name_of(pid: str) -> str:
        p = lobby.players.get(pid)
        return p.name if p else "—"

    return {
        "models": [{"name": k, "rating": round(v)} for k, v in models],
        "players": [{"name": name_of(k), "rating": round(v)} for k, v in players],
        "models_self_reported": True,          # model names are self-reported by players and can't be verified
    }


# ---------------- Persistence: player ratings (only secret hashes are stored) ----------------
def load_state() -> None:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            n = lobby.restore(json.load(f))
        log.info("restored %d players from %s", n, STATE_PATH)
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — a corrupt file must not stop the server from starting, but log it
        log.exception("restore lobby state failed")


def save_state(force: bool = False) -> None:
    if not (lobby.dirty or force):
        return
    parent = os.path.dirname(STATE_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lobby.dump(), f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)
    lobby.dirty = False
