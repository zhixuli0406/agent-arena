"""Local Docker provisioner. For development and live verification.

Isolation model (tested): the target and the attack runner share one --internal (no egress) network; the target
publishes no ports, and the engine drives the runner via docker exec to hit the target. The whole sandbox is sealed off.

Hard gates:
  G1 only provisions images on the targets/allowlist.yaml allowlist.
  G2 --internal network (no default route, the target can't reach the internet) + no published ports.
  G3 containers and the isolated network carry arena.match / arena.expires labels for the reaper; explicit teardown at match end.
  G4 injected env vars are scanned for real-looking credentials (the flag is exempt); any hit is rejected.
  Container hardening: --cap-drop ALL, --security-opt no-new-privileges, --pids-limit, --memory.
"""

from __future__ import annotations

import asyncio
import os
import time

import yaml

from ..security import looks_secret
from .base import Provisioner, Sandbox, TargetSpec

_PIPE = asyncio.subprocess.PIPE
_DEFAULT_ALLOWLIST = os.path.join(os.path.dirname(__file__), "..", "..", "targets", "allowlist.yaml")

# The runner sends requests with python urllib; method/url/body are passed as argv, no shell.
_FETCH = r"""
import sys, urllib.request, urllib.error
method, url = sys.argv[1], sys.argv[2]
body = sys.argv[3].encode() if len(sys.argv) > 3 and sys.argv[3] else None
req = urllib.request.Request(url, data=body, method=method)
try:
    r = urllib.request.urlopen(req, timeout=8)
    print(r.status); print(r.read().decode("utf-8", "replace"))
except urllib.error.HTTPError as e:
    print(e.code); print(e.read().decode("utf-8", "replace"))
except Exception as e:
    print(-1); print("ERR: %s: %s" % (type(e).__name__, e))
"""


async def _run(*argv: str, timeout: float = 60.0) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(*argv, stdout=_PIPE, stderr=_PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return (124, b"", b"timeout")
    return (proc.returncode or 0, out, err)


def _load_allowlist(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {img["name"]: img for img in data.get("images", [])}


class LocalDockerSandbox(Sandbox):
    def __init__(self, net: str, target: str, runner: str, base_url: str):
        self._net = net
        self._target = target
        self._runner = runner
        self._base = base_url
        self._down = False

    async def http(self, method: str, path: str, body: str | None = None, timeout: float = 12.0) -> tuple[int, str]:
        if not path.startswith("/"):
            path = "/" + path  # pinned to this match's target; agents can't hit other hosts
        url = self._base + path
        rc, out, err = await _run(
            "docker", "exec", self._runner, "python", "-c", _FETCH, method, url, body or "", timeout=timeout
        )
        if rc != 0:
            return (-1, f"runner error rc={rc}: {err.decode(errors='replace')[:200]}")
        text = out.decode(errors="replace")
        status_line, _, body_text = text.partition("\n")
        try:
            status = int(status_line.strip())
        except ValueError:
            status = -1
        return (status, body_text)

    async def teardown(self) -> None:
        if self._down:
            return
        self._down = True
        await _run("docker", "rm", "-f", self._target, timeout=30)
        await _run("docker", "rm", "-f", self._runner, timeout=30)
        await _run("docker", "network", "rm", self._net, timeout=30)


class LocalDockerProvisioner(Provisioner):
    def __init__(self, allowlist_path: str | None = None):
        self.allowlist = _load_allowlist(allowlist_path or os.environ.get("ARENA_ALLOWLIST", _DEFAULT_ALLOWLIST))

    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        rc, _, err = await _run("docker", "version", "--format", "{{.Server.Version}}", timeout=15)
        if rc != 0:
            raise RuntimeError(f"docker unavailable: {err.decode(errors='replace')[:120]}")

        # G1 allowlist
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(
                f"G1 rejected: image {target.image!r} is not on the allowlist ({', '.join(self.allowlist)})"
            )
        port = int(meta["port"])

        # G4 secret scan (the flag is exempt)
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 rejected: the value of env var {k} looks like a real credential")

        net = f"arena-{match_id}"
        tgt = f"arena-tgt-{match_id}"
        run = f"arena-run-{match_id}"
        expires = int(time.time()) + ttl_seconds
        labels = ["--label", f"arena.match={match_id}", "--label", f"arena.expires={expires}"]
        hard = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "512m"]

        # G2 no-egress network
        rc, _, err = await _run("docker", "network", "create", "--internal", *labels, net, timeout=30)
        if rc != 0:
            raise RuntimeError(f"creating the isolated network failed: {err.decode(errors='replace')[:160]}")

        env_args: list[str] = []
        for k, v in (target.env or {}).items():
            env_args += ["-e", f"{k}={v}"]

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", tgt, "--network", net, *labels, *hard, *env_args, target.image,
            timeout=120,
        )
        if rc != 0:
            await _run("docker", "network", "rm", net)
            raise RuntimeError(f"starting the target failed: {err.decode(errors='replace')[:160]}")

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", run, "--network", net, *labels, *hard,
            "python:3.12-alpine", "sleep", str(ttl_seconds),
            timeout=120,
        )
        if rc != 0:
            await _run("docker", "rm", "-f", tgt)
            await _run("docker", "network", "rm", net)
            raise RuntimeError(f"starting the runner failed: {err.decode(errors='replace')[:160]}")

        sandbox = LocalDockerSandbox(net, tgt, run, f"http://{tgt}:{port}")

        # wait for the target to be ready (polling through the runner)
        for _ in range(30):
            status, _body = await sandbox.http("GET", "/", timeout=8)
            if status != -1:
                break
            await asyncio.sleep(1)

        return sandbox
