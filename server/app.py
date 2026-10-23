"""Agent Arena match server (public edition).

  - Single entry point for player-brought agents: /api/connect/{token}/stream (SSE, receive questions), /api/connect/{token}/action (answer)
  - Online lobby: /api/lobby/* (queue and matchmaking, ready check, custom rooms, stats, spectate list, leaderboard)
  - Demo match: /api/demo (mock vs mock, fixed settings)
  - Spectating: /api/matches/{id}/stream (live transcript stream)
  - Frontend: /game/ (public UI and pixel theater)

The public server only accepts player-brought agents and demo agents; it never uses the server
owner's keys to play for anyone (see runtime.py). Custom match creation (POST /api/matches) is only
open on a private server, and only to local requests or the admin token.
Error messages follow Accept-Language: zh-TW / zh-CN / en / ja.

Run locally: uvicorn server.app:app --port 8799
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from arena.adapters.remote import get_slot
from arena.types import MatchConfig

from . import guard
from . import runtime as rt
from .i18n import SUPPORTED, I18nError, pick_lang
from .lobby_api import router as lobby_router

log = logging.getLogger("arena.server")


class _RedactTokenPath(logging.Filter):
    """uvicorn access logs print the full path: replace /api/connect/<token> with a placeholder so connection tokens never reach the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            args[2] = guard.redact_path(args[2])
            record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactTokenPath())

ADMIN_TOKEN = os.environ.get("ARENA_ADMIN_TOKEN", "")
DEFAULT_CORS = (
    r"^https://(zhixuli0406\.github\.io|([a-z0-9-]+\.)*claude\.ai|([a-z0-9-]+\.)*claudeusercontent\.com)$"
    r"|^http://(localhost|127\.0\.0\.1)(:\d+)?$"
)
LOCAL_CORS = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
# A private server (host adapters enabled) serves localhost only: CORS allows local pages only, Host must be local (blocks DNS rebinding)
CORS_REGEX = LOCAL_CORS if rt.ALLOW_HOST_ADAPTERS else os.environ.get("ARENA_CORS_REGEX", DEFAULT_CORS)


async def _matchmaker() -> None:
    n = 0
    while True:
        try:
            rt.lobby.tick()
            n += 1
            if n % 30 == 0:
                rt.save_state()                       # flush rating changes to disk every 30 seconds
            if n % 60 == 0:
                rt.reap()                             # reap expired matches and transcripts every minute
        except Exception:  # noqa: BLE001 — the matchmaking loop must not die, but log every failure
            log.exception("matchmaker tick failed")
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    rt.load_state()
    task = asyncio.create_task(_matchmaker())
    yield
    task.cancel()
    rt.save_state(force=True)


def _lang(request: Request) -> str:
    return pick_lang(request.headers.get("accept-language"))


def _error(request: Request, err: I18nError, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": err.text(_lang(request)), "code": err.key}, status_code=err.code, headers=headers)


def _origin_ok(request: Request) -> bool:
    """Allow POST only with no Origin (CLI clients, curl) or from an allowed web origin / same-origin page."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    if re.match(CORS_REGEX, origin):
        return True
    host = request.headers.get("host", "")
    return bool(host) and origin in (f"https://{host}", f"http://{host}")


class GuardMiddleware:
    """Pure ASGI middleware: rate limits and body size cap for /api/* (reads the body fully, then replays it, so a streamed body can't bypass the cap)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = scope["path"], scope["method"]
        ip = guard.client_ip(request)
        is_action = method == "POST" and path.startswith("/api/connect/") and path.endswith("/action")
        if method == "POST" and not _origin_ok(request):
            # Other sites can make a visitor's browser send POSTs (no-cors / forms); CORS blocks reading, not sending.
            # Reject before charging any route quota, so a malicious page can't burn the visitor's join/queue quota
            guard.security_event("foreign_origin", request, origin=request.headers.get("origin", "")[:100])
            return await _error(request, I18nError("bad_origin", 403))(scope, receive, send)
        checks = [("global_ip", ip), ("global", guard.client_key(request, ip))]
        checks += [(r, ip) for m, p, rules in guard.ROUTE_RULES if m == method and p == path for r in rules]
        if is_action:
            checks.append(("action", path.split("/")[3]))
        for rule, key in checks:
            wait = guard.limiter.hit(rule, key)
            if wait:
                if rule not in ("global", "global_ip"):
                    guard.security_event("rate_limited", request, rule=rule)
                resp = _error(request, I18nError("rate_limited", 429, s=int(wait) + 1), {"Retry-After": str(int(wait) + 1)})
                return await resp(scope, receive, send)
        if method in ("POST", "PUT", "PATCH"):
            limit = guard.MAX_ACTION_BODY if is_action else guard.MAX_BODY
            body, more = b"", True
            while more:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                body += msg.get("body", b"")
                more = msg.get("more_body", False)
                if len(body) > limit:
                    guard.security_event("body_too_large", request, size=len(body))
                    return await _error(request, I18nError("too_large", 413))(scope, receive, send)
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


app = FastAPI(title="Agent Arena", lifespan=lifespan)
app.add_middleware(GuardMiddleware)
if rt.ALLOW_HOST_ADAPTERS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
# CORS is added last = outermost: rate-limit and 413 responses also carry CORS headers, so browsers can read the error
app.add_middleware(
    CORSMiddleware, allow_origin_regex=CORS_REGEX, allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept-Language", "X-Player-Id", "X-Player-Secret"],
    expose_headers=["Retry-After"],
)
app.include_router(lobby_router)


@app.exception_handler(I18nError)
async def _i18n_error(request: Request, exc: I18nError) -> JSONResponse:
    return _error(request, exc)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "service": "agent-arena", "live_matches": rt.live_count(), **rt.lobby.stats()}


# ---------------- Demo match (public) and custom matches (private server only) ----------------
@app.post("/api/demo")
async def create_demo() -> dict:
    mid = rt.start_demo()
    return {"match_id": mid, "mode": "quiz", "players": rt.matches[mid]["players"]}


def _admin_ok(request: Request) -> bool:
    # Always require the admin token: a local connection is not proof of the owner; any web page in a browser can send requests to 127.0.0.1
    given = request.headers.get("x-admin-token", "")
    return bool(ADMIN_TOKEN) and secrets.compare_digest(given, ADMIN_TOKEN)


@app.post("/api/matches")
async def create_match(request: Request, body: dict) -> dict:
    # Disabled on the public server: an outside mode_config can carry arbitrary regex (ReDoS) and exhaust match slots; reserved for local/admin use on a private server
    if not rt.ALLOW_HOST_ADAPTERS:
        raise I18nError("private_only", 404)
    # Host adapters play using the owner's local logins: only for whoever holds ARENA_ADMIN_TOKEN (play-free.sh generates and sends it automatically)
    if not _admin_ok(request):
        guard.security_event("admin_denied", request)
        raise I18nError("admin_only", 403)
    try:
        cfg = MatchConfig.from_dict(body)
    except Exception as e:  # noqa: BLE001 — boundary validation, return 400 to the caller
        raise I18nError("bad_config", 400, e=type(e).__name__) from e
    cfg.ratings_path = ""                     # the server alone picks the ladder file path; callers can't choose where it writes
    connect: dict[str, dict] = {}
    for s in cfg.agents:
        if s.adapter == "remote":
            tok = secrets.token_urlsafe(12)   # tokens are always generated by the server
            s.params["token"] = tok
            connect[s.id] = {"token": tok, "stream": f"/api/connect/{tok}/stream",
                             "action": f"/api/connect/{tok}/action"}
    mid = rt.start_match(cfg, meta={"source": "api"})
    return {"match_id": mid, "mode": cfg.mode, "connect": connect}


def _known_match(match_id: str) -> dict:
    if not rt.MATCH_ID_RE.match(match_id) or match_id not in rt.matches:
        raise I18nError("unknown_match", 404)
    return rt.matches[match_id]


@app.get("/api/matches/{match_id}")
async def match_status(match_id: str) -> JSONResponse:
    m = _known_match(match_id)
    task: asyncio.Task = m["task"]
    if not task.done():
        return JSONResponse({"status": "RUNNING"})
    if task.cancelled() or task.exception() is not None:
        return JSONResponse({"status": "ERROR"})       # exception details go to the server log only
    rep = task.result()
    return JSONResponse({
        "status": rep.status,
        "result": {"scores": rep.result.scores, "ranking": rep.result.ranking} if rep.result else None,
        "elo_deltas": rep.elo_deltas,
        "degraded": rep.degraded_reasons,
        "forfeits": rep.forfeits,
        "rated": rep.rated,
    })


@app.get("/api/matches/{match_id}/stream")
async def match_stream(request: Request, match_id: str) -> StreamingResponse:
    _known_match(match_id)
    ip = guard.client_ip(request)
    if not guard.streams.acquire("ip:" + ip, guard.MAX_STREAMS_PER_IP):
        raise I18nError("too_many_streams", 429)
    path = os.path.join(rt.RUNS_DIR, match_id + ".jsonl")

    async def gen():
        try:
            for _ in range(50):
                if os.path.exists(path):
                    break
                await asyncio.sleep(0.2)
            offset = 0
            while True:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    if chunk:
                        if not chunk.endswith(b"\n"):          # partial line: put it back and wait for the next read
                            partial = chunk.split(b"\n")[-1]
                            offset -= len(partial)
                            chunk = chunk[: len(chunk) - len(partial)]
                        for raw in chunk.decode("utf-8", "replace").split("\n"):
                            if raw.strip():
                                yield f"data: {raw}\n\n"
                task = rt.matches.get(match_id, {}).get("task")
                if task is None or (task.done() and os.path.exists(path) and offset >= os.path.getsize(path)):
                    break
                await asyncio.sleep(0.25)
            yield "event: end\ndata: {}\n\n"
        finally:
            guard.streams.release("ip:" + ip)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- Player-brought agents: unified connection protocol ----------------
def _obs_payload(obs, lang: str) -> str:
    loc = (obs.state or {}).get("i18n", {}).get(lang) or {}
    return json.dumps({"round": obs.round, "task": loc.get("task", obs.task),
                       "instructions": loc.get("instructions", obs.instructions), "lang": lang},
                      ensure_ascii=False)


def _stream_lang(request: Request, lang: str | None) -> str:
    if lang in SUPPORTED:
        return lang
    return _lang(request)


@app.get("/api/connect/{token}/stream")
async def connect_stream(request: Request, token: str, lang: str | None = None) -> StreamingResponse:
    if token not in rt.valid_tokens:
        raise I18nError("bad_token", 404)
    if not guard.streams.acquire("tok:" + token, guard.MAX_STREAMS_PER_TOKEN):
        raise I18nError("too_many_streams", 429)
    slot = get_slot(token)
    use_lang = _stream_lang(request, lang)

    async def gen():
        # State broadcast: every connection reads the same slot state, so reconnects, multiple windows or stale connections can't steal a question or the end signal
        slot.connections += 1
        try:
            yield "event: hello\ndata: {}\n\n"
            seen = -1                                     # send the current state on connect (catch-up after reconnect)
            while True:
                if slot.ended:
                    yield "event: end\ndata: {}\n\n"
                    return
                if slot.version != seen:
                    seen = slot.version
                    if slot.current is not None:
                        yield f"data: {_obs_payload(slot.current, use_lang)}\n\n"
                    continue
                if not await slot.wait_change(seen, 15):
                    yield ": ping\n\n"                    # heartbeat so proxies/firewalls don't drop the connection
        finally:
            slot.connections -= 1
            guard.streams.release("tok:" + token)

    return StreamingResponse(gen(), media_type="text/event-stream")


ACTION_MAX_CHARS = 4000


@app.post("/api/connect/{token}/action")
async def connect_action(token: str, body: dict) -> dict:
    if token not in rt.valid_tokens:
        raise I18nError("bad_token", 404)
    slot = get_slot(token)
    if slot.ended:
        raise I18nError("match_ended", 410)
    rnd = body.get("round")
    if rnd is not None and (isinstance(rnd, bool) or not re.fullmatch(r"-?\d{1,9}", str(rnd).strip())):
        raise I18nError("bad_round", 400)
    content = body.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content)
    try:
        slot.actions.put_nowait((int(rnd) if rnd is not None else None, content[:ACTION_MAX_CHARS]))
    except asyncio.QueueFull as e:
        raise I18nError("answers_full", 429) from e
    return {"ok": True}


# The frontend (public UI, pixel theater) ships in the same deployment as the API
if os.path.isdir("web"):
    app.mount("/game", StaticFiles(directory="web", html=True), name="game")
