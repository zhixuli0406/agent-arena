"""Free-hosting target provisioner: Docker runs the target + a Cloudflare quick tunnel makes it public (no account, no credit card).

Puts security-match targets on free hosting too. Security boundary: only allowlisted self-hosted benign targets with
kind=self (the warmup target only hands out a fake flag); truly vulnerable OSS images must not be made public and
stay local and private (see docs/SAFETY.md).

G3 cleanup: containers carry arena.match / arena.expires labels (the reaper cleans up by them), and an in-process timer tears them down when the TTL expires.
Binding: the target port is published only on 127.0.0.1 (docker picks a free port, so there's no probe-then-bind race),
and cloudflared connects to 127.0.0.1 explicitly rather than localhost (so it can't resolve to ::1 and get hijacked by another process binding there).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time

from ..security import looks_secret
from .base import Provisioner, Sandbox, TargetSpec
from .local import _DEFAULT_ALLOWLIST, _load_allowlist, _run

_URL_RE = re.compile(rb"https://[-a-z0-9]+\.trycloudflare\.com")


_LOOPBACK = "127.0.0.1"
_BACKGROUND: set[asyncio.Task] = set()


def parse_docker_port(output: bytes | str) -> int:
    """Parse `docker port <c> <p>/tcp` output, accepting only the line bound to 127.0.0.1."""
    text = output.decode(errors="replace") if isinstance(output, bytes) else output
    for line in text.splitlines():
        host, _, port = line.strip().rpartition(":")
        if host == _LOOPBACK and port.isdigit():
            return int(port)
    raise RuntimeError(f"no published port bound to {_LOOPBACK}: {text[:120]!r}")


class TunnelSandbox(Sandbox):
    def __init__(self, base_url: str, container: str, cf_proc: asyncio.subprocess.Process,
                 ttl_seconds: float | None = None):
        self._base = base_url.rstrip("/")
        self._container = container
        self._cf = cf_proc
        self._down = False
        self._ttl_handle: asyncio.TimerHandle | None = None
        # keep draining cloudflared's log after getting the URL, or a full pipe stalls the tunnel
        self._drain: asyncio.Task | None = (
            asyncio.ensure_future(_drain(cf_proc.stdout)) if cf_proc is not None and cf_proc.stdout else None
        )
        if ttl_seconds and ttl_seconds > 0:
            # enforce the TTL: even if the match forgets to tear down, the public target is removed when it expires
            loop = asyncio.get_running_loop()
            self._ttl_handle = loop.call_later(ttl_seconds, self._ttl_expired)

    def _ttl_expired(self) -> None:
        task = asyncio.ensure_future(self.teardown())
        _BACKGROUND.add(task)  # keep a reference so the task isn't garbage-collected midway
        task.add_done_callback(_BACKGROUND.discard)

    @property
    def public_url(self) -> str:
        return self._base

    async def http(self, method: str, path: str, body: str | None = None, timeout: float = 15.0) -> tuple[int, str]:
        import httpx

        if not path.startswith("/"):
            path = "/" + path
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                resp = await client.request(method, self._base + path, content=(body.encode() if body else None))
                return (resp.status_code, resp.text)
        except Exception as e:  # noqa: BLE001
            return (-1, f"ERR: {type(e).__name__}: {e}")

    async def teardown(self) -> None:
        if self._down:
            return
        self._down = True
        if self._ttl_handle is not None:
            self._ttl_handle.cancel()
        await _stop_tunnel(self._cf)
        if self._drain is not None:
            self._drain.cancel()
        await _run("docker", "rm", "-f", self._container, timeout=30)


async def _drain(stream: asyncio.StreamReader) -> None:
    try:
        while await stream.readline():
            pass
    except Exception:  # noqa: BLE001 — only discarding logs; a failure doesn't affect the match
        return


async def _stop_tunnel(cf: asyncio.subprocess.Process | None) -> None:
    """terminate first, kill if it doesn't exit, so the public tunnel is always closed."""
    if cf is None or cf.returncode is not None:
        return
    try:
        cf.terminate()
        await asyncio.wait_for(cf.wait(), timeout=5)
    except ProcessLookupError:
        return
    except asyncio.TimeoutError:
        try:
            cf.kill()
        except ProcessLookupError:
            pass


class FreeHostProvisioner(Provisioner):
    def __init__(self, allowlist_path: str | None = None):
        self.allowlist = _load_allowlist(allowlist_path or os.environ.get("ARENA_ALLOWLIST", _DEFAULT_ALLOWLIST))

    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(f"G1 rejected: image {target.image!r} is not on the allowlist")
        if meta.get("kind") != "self":
            raise PermissionError("public targets on free hosting are limited to self-hosted benign self targets; use local for truly vulnerable images and keep them private (SAFETY.md)")
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 rejected: env var {k} looks like a real credential")
        if shutil.which("cloudflared") is None:
            raise RuntimeError("cloudflared is required (brew install cloudflared)")
        rc, _, err = await _run("docker", "version", "--format", "{{.Server.Version}}", timeout=15)
        if rc != 0:
            raise RuntimeError(f"docker unavailable: {err.decode(errors='replace')[:120]}")

        port = int(meta["port"])
        name = f"arena-tgt-{match_id}"
        expires = int(time.time()) + int(ttl_seconds)
        labels = ["--label", f"arena.match={match_id}", "--label", f"arena.expires={expires}"]
        hard = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "512m"]
        env_args: list[str] = []
        for k, v in (target.env or {}).items():
            env_args += ["-e", f"{k}={v}"]

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", name, "-p", f"{_LOOPBACK}::{port}", *labels, *hard, *env_args,
            target.image, timeout=120,
        )
        if rc != 0:
            raise RuntimeError(f"starting the target failed: {err.decode(errors='replace')[:160]}")
        rc, out, err = await _run("docker", "port", name, f"{port}/tcp", timeout=15)
        try:
            if rc != 0:
                raise RuntimeError(f"querying the published port failed: {err.decode(errors='replace')[:120]}")
            hostport = parse_docker_port(out)
        except Exception:
            await _run("docker", "rm", "-f", name)
            raise

        cf = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://{_LOOPBACK}:{hostport}", "--no-autoupdate",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        url: str | None = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                line = await asyncio.wait_for(cf.stdout.readline(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            m = _URL_RE.search(line)
            if m:
                url = m.group().decode()
                break
        if not url:
            await _stop_tunnel(cf)
            await _run("docker", "rm", "-f", name)
            raise RuntimeError("timed out waiting for cloudflared's public URL")

        sandbox = TunnelSandbox(url, name, cf, ttl_seconds=ttl_seconds)
        for _ in range(30):  # wait for the target to be ready (via the public URL)
            status, _body = await sandbox.http("GET", "/", timeout=10)
            if status not in (-1, 502, 503):
                break
            await asyncio.sleep(1)
        return sandbox
