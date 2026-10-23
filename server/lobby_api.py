"""Lobby API: join, parties, queue and matchmaking (free-for-all / team), ready check, custom rooms, stats, spectate list, leaderboard.

Auth: on join a player gets a player_id and secret; later calls send the X-Player-Id / X-Player-Secret headers.
Connection tokens (for attaching an agent) are returned only to their owner. All errors raise I18nError, which the app translates per Accept-Language.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from . import guard
from . import runtime as rt
from .agents import public_item
from .i18n import SUPPORTED, I18nError
from .lobby import FORMATS, MODES, ROOM_CODE_LEN, SIZES, TEAM_FORMATS, Player, _hash
from .party import PARTY_MAX, PARTY_SPREAD

router = APIRouter(prefix="/api/lobby", tags=["lobby"])
# Cross common proxy buffering thresholds with short lines that streaming clients can consume.
SSE_PROXY_PADDING = (": " + (" " * 510) + "\n") * 256 + "\n"


def _me(request: Request, pid: str | None, secret: str | None) -> Player:
    return rt.lobby.auth(pid or "", secret or "", ip=guard.client_ip(request))


def _no_token(view: dict) -> dict:
    """Seat tokens only travel over the player's agent stream; lobby views never carry them."""
    view.pop("token", None)
    return view


def _require_agents(player_ids: list[str]) -> None:
    """Players must bring their own agent: every seat being filled needs that player's agent online,
    and nobody can be pulled into a new match while still seated in a running one (their agent would
    drop the live match, forfeiting every question left)."""
    busy = [rt.lobby.players[pid].name for pid in player_ids if pid in rt.lobby.players and rt.live_match_of(pid)]
    if busy:
        raise I18nError("in_match", 409, names="、".join(busy))
    off = [rt.lobby.players[pid].name for pid in player_ids if pid in rt.lobby.players and not rt.hub.online(pid)]
    if off:
        raise I18nError("agent_offline", 409, names="、".join(off))


def _int(body: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(body.get(key, default))
    except (TypeError, ValueError) as e:
        raise I18nError("bad_field", 400, field=key) from e


@router.get("/config")
async def config() -> dict:
    return {"modes": list(MODES), "sizes": list(SIZES), "formats": list(FORMATS), "team_formats": TEAM_FORMATS,
            "party_max": PARTY_MAX, "party_spread": PARTY_SPREAD,
            "langs": list(SUPPORTED), "room_code_len": ROOM_CODE_LEN}


@router.post("/players")
async def register(request: Request, body: dict) -> dict:
    p = rt.lobby.register(str(body.get("name", "")), str(body.get("agent", "")), ip=guard.client_ip(request))
    return {"player": rt.lobby.public(p), "secret": p.secret}


@router.get("/me")
async def me(request: Request, x_player_id: str | None = Header(None), x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    t = rt.lobby.active_ticket(p.id)
    r = rt.lobby.room_of(p.id)
    party = rt.lobby.party_of(p.id)
    return {"player": rt.lobby.public(p), "agent_online": rt.hub.online(p.id),
            "ticket": _no_token(rt.lobby.ticket_view(t, p.id)) if t else None,
            "room": _no_token(rt.lobby.room_view(r, p.id)) if r else None,
            "party": rt.lobby.party_view(party, p.id) if party else None}


# ---------------- Agent link + standby channel ----------------
@router.post("/link")
async def create_link(request: Request, x_player_id: str | None = Header(None), x_player_secret: str | None = Header(None)) -> dict:
    """One-time code to hand this player to an agent (or, from an agent, to a browser)."""
    p = _me(request, x_player_id, x_player_secret)
    code, ttl = rt.lobby.create_link(p)
    return {"code": code, "expires_in": int(ttl)}


@router.post("/link/redeem")
async def redeem_link(body: dict) -> dict:
    p, secret = rt.lobby.redeem_link(str(body.get("code", "")))
    return {"player": rt.lobby.public(p), "secret": secret}


@router.post("/credentials/reset")
async def reset_credentials(request: Request, x_player_id: str | None = Header(None),
                            x_player_secret: str | None = Header(None)) -> dict:
    """Sign out every linked agent and every other browser; only the caller's credential keeps working."""
    p = _me(request, x_player_id, x_player_secret)
    rt.lobby.reset_credentials(p, x_player_secret or "")
    rt.hub.sign_out(p.id, keep=_hash(x_player_secret or ""))
    return {"ok": True}


@router.get("/agent/stream")
async def agent_stream(request: Request, x_player_id: str | None = Header(None),
                       x_player_secret: str | None = Header(None)) -> StreamingResponse:
    p = _me(request, x_player_id, x_player_secret)
    key, ip_key = "agent:" + p.id, "agentip:" + guard.client_ip(request)
    if not guard.streams.acquire(key, guard.MAX_AGENT_STREAMS):
        raise I18nError("too_many_streams", 429)
    if not guard.streams.acquire(ip_key, guard.MAX_AGENT_STREAMS_PER_IP):
        guard.streams.release(key)
        raise I18nError("too_many_streams", 429)
    pid, cred = p.id, _hash(x_player_secret or "")

    async def gen():
        rt.hub.connect(pid, cred)
        try:
            # Put hello first so it is in the first proxy flush; the following valid SSE comments provide
            # enough bytes to cross buffering thresholds without creating an over-long client input line.
            yield f"event: hello\ndata: {json.dumps({'player': rt.lobby.public(p)}, ensure_ascii=False)}\n\n"
            yield SSE_PROXY_PADDING
            seen = 0
            while rt.lobby.has_credential(pid, cred):        # signed out ("sign out all agents" / evicted): stop dispatching
                for item in rt.hub.pending(pid, seen):
                    seen = max(seen, item["_id"])
                    yield f"event: match\ndata: {json.dumps(public_item(item), ensure_ascii=False)}\n\n"
                if not await rt.hub.wait(pid, seen, 15):
                    yield ": ping\n\n"                       # heartbeat; also how we notice a dead connection
                if await request.is_disconnected():
                    return
        except asyncio.CancelledError:
            return
        finally:
            rt.hub.disconnect(pid, cred)
            guard.streams.release(key)
            guard.streams.release(ip_key)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# ---------------- Matchmaking ----------------
@router.post("/queue")
async def enqueue(request: Request, body: dict, x_player_id: str | None = Header(None),
                  x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    fmt = str(body.get("format", "ffa"))
    party = rt.lobby.party_of(p.id)
    _require_agents(list(party.members) if party and fmt != "ffa" else [p.id])
    t = rt.lobby.enqueue(p, str(body.get("mode", "quiz")), _int(body, "size", 2), ip=guard.client_ip(request), fmt=fmt)
    return _no_token(rt.lobby.ticket_view(t, p.id))


@router.get("/tickets/{ticket_id}")
async def ticket(request: Request, ticket_id: str, x_player_id: str | None = Header(None),
                 x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    return _no_token(rt.lobby.ticket_view(rt.lobby.ticket_of(p, ticket_id), p.id))


@router.post("/tickets/{ticket_id}/{action}")
async def ticket_action(request: Request, ticket_id: str, action: str, x_player_id: str | None = Header(None),
                        x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    t = rt.lobby.ticket_of(p, ticket_id)
    ops = {"accept": rt.lobby.accept, "decline": rt.lobby.decline, "cancel": rt.lobby.cancel}
    if action not in ops:
        raise I18nError("unknown_action", 404)
    if action == "accept":
        _require_agents([p.id])                  # accepting a seat you can't play would only forfeit every question
    ops[action](t, p)
    return _no_token(rt.lobby.ticket_view(t, p.id))


# ---------------- Parties (for the team queue; members stay on the same side) ----------------
@router.post("/parties")
async def create_party(request: Request, x_player_id: str | None = Header(None), x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    return rt.lobby.party_view(rt.lobby.create_party(p), p.id)


@router.get("/parties/{code}")
async def party(request: Request, code: str, x_player_id: str | None = Header(None),
                x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)          # party details are for members only
    return rt.lobby.party_view(rt.lobby.member_party(code, p), p.id)


@router.post("/parties/{code}/{action}")
async def party_action(request: Request, code: str, action: str, body: dict | None = None,
                       x_player_id: str | None = Header(None),
                       x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    body = body or {}
    if action == "join":
        return rt.lobby.party_view(rt.lobby.join_party(code, p), p.id)
    if action == "leave":
        rt.lobby.member_party(code, p)
        rt.lobby.leave_party(p)
        return {"left": True}
    if action == "kick":
        rt.lobby.member_party(code, p)
        return rt.lobby.party_view(rt.lobby.kick_from_party(p, str(body.get("player_id", ""))), p.id)
    raise I18nError("unknown_action", 404)


# ---------------- Custom rooms (not counted on the ladder) ----------------
@router.post("/rooms")
async def create_room(request: Request, body: dict, x_player_id: str | None = Header(None),
                      x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    r = rt.lobby.create_room(p, str(body.get("mode", "quiz")), _int(body, "size", 4))
    return _no_token(rt.lobby.room_view(r, p.id))


@router.get("/rooms/{code}")
async def room(request: Request, code: str, x_player_id: str | None = Header(None),
               x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)          # room details are for room members only
    return _no_token(rt.lobby.room_view(rt.lobby.member_room(code, p), p.id))


@router.post("/rooms/{code}/{action}")
async def room_action(request: Request, code: str, action: str, body: dict | None = None,
                      x_player_id: str | None = Header(None),
                      x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    body = body or {}
    if action == "join":
        r = rt.lobby.join_room(code, p)
    elif action == "leave":
        rt.lobby.leave_room(code, p)
        return {"left": True}
    elif action == "ready":
        if bool(body.get("ready", True)):
            _require_agents([p.id])
        r = rt.lobby.set_ready(code, p, bool(body.get("ready", True)))
    elif action == "start":
        _require_agents(list(rt.lobby.member_room(code, p).members))
        r = rt.lobby.start_room(code, p)
    elif action == "kick":
        r = rt.lobby.kick(code, p, str(body.get("player_id", "")))
    else:
        raise I18nError("unknown_action", 404)
    return _no_token(rt.lobby.room_view(r, p.id))


# ---------------- Public info ----------------
@router.get("/stats")
async def stats() -> dict:
    return {**rt.lobby.stats(), "live_matches": rt.live_count()}


@router.get("/matches")
async def matches() -> dict:
    return {"matches": rt.recent_matches()}


@router.get("/leaderboard")
async def leaderboard() -> dict:
    return rt.leaderboard()
