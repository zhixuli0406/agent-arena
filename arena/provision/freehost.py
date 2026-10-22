"""免費空間靶機配置器：Docker 跑靶機 + Cloudflare quick tunnel 公開（零帳號、零信用卡）。

把「資安場靶機」也架到免費空間。安全邊界：只收白名單中 kind=self 的自架 benign 靶機
（暖身靶機只吐假 flag）；真正脆弱的 OSS 映像不得公開，仍留本機私有（見 docs/SAFETY.md）。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
import time

from ..security import looks_secret
from .base import Provisioner, Sandbox, TargetSpec
from .local import _DEFAULT_ALLOWLIST, _load_allowlist, _run

_URL_RE = re.compile(rb"https://[-a-z0-9]+\.trycloudflare\.com")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TunnelSandbox(Sandbox):
    def __init__(self, base_url: str, container: str, cf_proc: asyncio.subprocess.Process):
        self._base = base_url.rstrip("/")
        self._container = container
        self._cf = cf_proc
        self._down = False

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
        if self._cf and self._cf.returncode is None:
            try:
                self._cf.terminate()
            except ProcessLookupError:
                pass
        await _run("docker", "rm", "-f", self._container, timeout=30)


class FreeHostProvisioner(Provisioner):
    def __init__(self, allowlist_path: str | None = None):
        self.allowlist = _load_allowlist(allowlist_path or os.environ.get("ARENA_ALLOWLIST", _DEFAULT_ALLOWLIST))

    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(f"G1 拒絕：映像 {target.image!r} 不在白名單")
        if meta.get("kind") != "self":
            raise PermissionError("免費空間公開靶機僅限自架 benign self 靶機；真正脆弱映像請用 local 留本機私有（SAFETY.md）")
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 拒絕：環境變數 {k} 疑似真實憑證")
        if shutil.which("cloudflared") is None:
            raise RuntimeError("需要 cloudflared（brew install cloudflared）")
        rc, _, err = await _run("docker", "version", "--format", "{{.Server.Version}}", timeout=15)
        if rc != 0:
            raise RuntimeError(f"docker 不可用：{err.decode(errors='replace')[:120]}")

        port = int(meta["port"])
        hostport = _free_port()
        name = f"arena-tgt-{match_id}"
        hard = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "512m"]
        env_args: list[str] = []
        for k, v in (target.env or {}).items():
            env_args += ["-e", f"{k}={v}"]

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{hostport}:{port}", *hard, *env_args, target.image,
            timeout=120,
        )
        if rc != 0:
            raise RuntimeError(f"啟動靶機失敗：{err.decode(errors='replace')[:160]}")

        cf = await asyncio.create_subprocess_exec(
            "cloudflared", "tunnel", "--url", f"http://localhost:{hostport}", "--no-autoupdate",
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
            try:
                cf.terminate()
            except ProcessLookupError:
                pass
            await _run("docker", "rm", "-f", name)
            raise RuntimeError("cloudflared 取得公開網址逾時")

        sandbox = TunnelSandbox(url, name, cf)
        for _ in range(30):  # 等靶機就緒（經公開網址）
            status, _body = await sandbox.http("GET", "/", timeout=10)
            if status not in (-1, 502, 503):
                break
            await asyncio.sleep(1)
        return sandbox
