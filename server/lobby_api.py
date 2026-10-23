"""Lobby API: join, parties, queue and matchmaking (free-for-all / team), ready check, custom rooms, stats, spectate list, leaderboard.

Auth: on join a player gets a player_id and secret; later calls send the X-Player-Id / X-Player-Secret headers.
Connection tokens (for attaching an agent) are returned only to their owner. All errors raise I18nError, which the app translates per Accept-Language.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request

from . import guard
from . import runtime as rt
from .i18n import SUPPORTED, I18nError
from .lobby import FORMATS, MODES, ROOM_CODE_LEN, SIZES, TEAM_FORMATS, Player
from .party import PARTY_MAX, PARTY_SPREAD

router = APIRouter(prefix="/api/lobby", tags=["lobby"])


def _me(request: Request, pid: str | None, secret: str | None) -> Player:
    return rt.lobby.auth(pid or "", secret or "", ip=guard.client_ip(request))


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
    return {"player": rt.lobby.public(p),
            "ticket": rt.lobby.ticket_view(t, p.id) if t else None,
            "room": rt.lobby.room_view(r, p.id) if r else None,
            "party": rt.lobby.party_view(party, p.id) if party else None}


# ---------------- Matchmaking ----------------
@router.post("/queue")
async def enqueue(request: Request, body: dict, x_player_id: str | None = Header(None),
                  x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    t = rt.lobby.enqueue(p, str(body.get("mode", "quiz")), _int(body, "size", 2), ip=guard.client_ip(request),
                         fmt=str(body.get("format", "ffa")))
    return rt.lobby.ticket_view(t, p.id)


@router.get("/tickets/{ticket_id}")
async def ticket(request: Request, ticket_id: str, x_player_id: str | None = Header(None),
                 x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    return rt.lobby.ticket_view(rt.lobby.ticket_of(p, ticket_id), p.id)


@router.post("/tickets/{ticket_id}/{action}")
async def ticket_action(request: Request, ticket_id: str, action: str, x_player_id: str | None = Header(None),
                        x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)
    t = rt.lobby.ticket_of(p, ticket_id)
    ops = {"accept": rt.lobby.accept, "decline": rt.lobby.decline, "cancel": rt.lobby.cancel}
    if action not in ops:
        raise I18nError("unknown_action", 404)
    ops[action](t, p)
    return rt.lobby.ticket_view(t, p.id)


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
    return rt.lobby.room_view(r, p.id)


@router.get("/rooms/{code}")
async def room(request: Request, code: str, x_player_id: str | None = Header(None),
               x_player_secret: str | None = Header(None)) -> dict:
    p = _me(request, x_player_id, x_player_secret)          # room details are for room members only
    return rt.lobby.room_view(rt.lobby.member_room(code, p), p.id)


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
        r = rt.lobby.set_ready(code, p, bool(body.get("ready", True)))
    elif action == "start":
        r = rt.lobby.start_room(code, p)
    elif action == "kick":
        r = rt.lobby.kick(code, p, str(body.get("player_id", "")))
    else:
        raise I18nError("unknown_action", 404)
    return rt.lobby.room_view(r, p.id)


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
