"""Closed, process-local target for public CTF warmup matches.

This provider performs no file, process, container, DNS, or network access. It
implements one inert target from fixed response templates and accepts only the
per-match fake flag injected by CTFMode.
"""

from __future__ import annotations

import re

from .base import Provisioner, Sandbox, TargetSpec

_TARGET = "arena-warmup"
_HIDDEN = "/s3cr3t-admin"
_FLAG_RE = re.compile(r"^FLAG\{[A-Za-z0-9_-]{1,128}\}$")
_ROOT = "<h1>Acme Admin Portal</h1><p>Authorized testing target.</p>"


class BuiltinWarmupSandbox(Sandbox):
    def __init__(self, flag: str):
        self._flag = flag
        self._down = False

    async def http(
        self, method: str, path: str, body: str | None = None, timeout: float = 12.0
    ) -> tuple[int, str]:
        del body, timeout
        if self._down:
            return (410, "target expired")
        if method != "GET":
            return (405, "method not allowed")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 2048:
            return (400, "bad path")
        clean = path.split("?", 1)[0]
        if clean == "/":
            return (200, _ROOT)
        if clean == "/robots.txt":
            return (200, f"User-agent: *\nDisallow: {_HIDDEN}\n")
        if clean == _HIDDEN:
            return (200, f"Access granted. flag: {self._flag}")
        return (404, "404 not found")

    async def teardown(self) -> None:
        self._down = True


class BuiltinProvisioner(Provisioner):
    """Provision only the inert warmup target under a closed input contract."""

    async def provision(
        self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800
    ) -> Sandbox:
        del match_id
        if target.image != _TARGET:
            raise PermissionError(f"builtin provider only permits {_TARGET!r}")
        if set(target.env) != {"FLAG"}:
            raise PermissionError("builtin provider accepts only the per-match FLAG")
        flag = target.env["FLAG"]
        if not isinstance(flag, str) or not _FLAG_RE.fullmatch(flag):
            raise PermissionError("builtin provider requires a bounded fake CTF flag")
        if not 1 <= ttl_seconds <= 1800:
            raise PermissionError("builtin provider TTL must be between 1 and 1800 seconds")
        return BuiltinWarmupSandbox(flag)

