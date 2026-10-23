"""Public server protection: client IP resolution, rate limits, request size caps, SSE connection caps, security event logging.

Behind a Cloudflare tunnel, every request's TCP source is localhost (cloudflared);
the real source is in the CF-Connecting-IP header, which Cloudflare overwrites. A request counts as local only if its TCP source is localhost and it has no forwarding headers.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import Request

sec_log = logging.getLogger("arena.security")

FORWARD_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip", "forwarded")
MAX_BODY = 64 * 1024              # body cap for general requests
MAX_ACTION_BODY = 8 * 1024        # body cap for answers


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    if _is_loopback(peer):
        cf = request.headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf[:64]
    return peer or "unknown"


def is_local(request: Request) -> bool:
    peer = request.client.host if request.client else None
    return _is_loopback(peer) and not any(h in request.headers for h in FORWARD_HEADERS)


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window: float     # seconds


# Each rule counts separately (fixed window). The key is usually the IP; answers use the token.
RULES = {
    # Two tiers: each player (or connection token) gets its own budget, and one IP has a combined cap.
    # Players behind the same home router (now encouraged to party up) would otherwise exhaust a shared
    # per-IP budget just by polling the lobby. Forged player ids only add buckets under the same IP cap.
    "global": Rule("global", 180, 60),
    "global_ip": Rule("global_ip", 900, 60),
    "register_h": Rule("register_h", 5, 3600),
    "register_d": Rule("register_d", 20, 86400),
    "room_create": Rule("room_create", 10, 3600),
    "queue": Rule("queue", 30, 3600),
    "action": Rule("action", 10, 1),
    "demo": Rule("demo", 6, 3600),
    "link": Rule("link", 20, 3600),
    "redeem": Rule("redeem", 30, 3600),        # 8-char codes from 31 symbols: guessing at this rate is hopeless
}


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[tuple[str, str], tuple[float, int]] = {}
        self._last_sweep = 0.0

    def hit(self, rule_name: str, key: str) -> float:
        """Record one hit; return seconds to wait (>0) if over the limit, else 0."""
        rule = RULES[rule_name]
        now = self._clock()
        self._sweep(now)
        start, count = self._buckets.get((rule_name, key), (now, 0))
        if now - start >= rule.window:
            start, count = now, 0
        if count >= rule.limit:
            return max(1.0, rule.window - (now - start))
        self._buckets[(rule_name, key)] = (start, count + 1)
        return 0.0

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        for k, (start, _) in list(self._buckets.items()):
            if now - start >= RULES[k[0]].window:
                self._buckets.pop(k, None)

    def reset(self) -> None:
        self._buckets.clear()


limiter = RateLimiter()

# Extra rules by path and method (site-wide rules always apply)
ROUTE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("POST", "/api/lobby/players", ("register_h", "register_d")),
    ("POST", "/api/lobby/rooms", ("room_create",)),
    ("POST", "/api/lobby/parties", ("room_create",)),       # creating parties and rooms share one quota
    ("POST", "/api/lobby/queue", ("queue",)),
    ("POST", "/api/demo", ("demo",)),
    ("POST", "/api/lobby/link", ("link",)),
    ("POST", "/api/lobby/link/redeem", ("redeem",)),
    ("POST", "/api/lobby/credentials/reset", ("link",)),
]


class StreamCounter:
    """Concurrent SSE connections: capped per key (IP or token)."""

    def __init__(self) -> None:
        self.open: dict[str, int] = defaultdict(int)

    def acquire(self, key: str, limit: int) -> bool:
        if self.open[key] >= limit:
            return False
        self.open[key] += 1
        return True

    def release(self, key: str) -> None:
        self.open[key] -= 1
        if self.open[key] <= 0:
            self.open.pop(key, None)


streams = StreamCounter()
MAX_STREAMS_PER_IP = 6
MAX_STREAMS_PER_TOKEN = 3
MAX_AGENT_STREAMS = 2        # standby streams per player (one agent, plus room for a reconnect)
MAX_AGENT_STREAMS_PER_IP = 8 # standby streams per network (a household of players, each with an agent)


def client_key(request: Request, ip: str) -> str:
    """Per-client rate-limit key: the claimed player id, or the connection token in /api/connect/ paths."""
    path = request.url.path
    if path.startswith("/api/connect/"):
        return f"{ip}|t:{path.split('/')[3][:64]}"
    pid = (request.headers.get("x-player-id") or "")[:40]
    return f"{ip}|p:{pid}" if pid else ip


def redact_path(path: str) -> str:
    """Connection tokens appear in the URL path: replace them with a placeholder before logging."""
    return re.sub(r"^/api/connect/[^/?]+(?=[/?]|$)", "/api/connect/{token}", path)


def security_event(kind: str, request: Request, **extra: object) -> None:
    """Security events record only the source, path and kind, never the body or credentials."""
    path = redact_path(request.url.path)
    sec_log.warning("security_event kind=%s ip=%s path=%s %s", kind, client_ip(request), path,
                    " ".join(f"{k}={v}" for k, v in extra.items()))
