"""本機 Docker 配置器。開發與活體驗證用。

隔離模型（已實測）：靶機與「攻擊 runner」掛在同一個 --internal（無出網）網路，
靶機不對外發佈任何埠，引擎透過 docker exec 驅動 runner 去打靶機。整個沙箱對外完全封閉。

硬性關卡：
  G1 只配置 targets/allowlist.yaml 白名單內的映像。
  G2 --internal 網路（無預設路由，靶機連不到外網）＋ 不發佈埠。
  G3 容器掛 arena.match / arena.expires 標籤，供 reaper 回收；散場顯式 teardown。
  G4 注入環境變數掃描疑似真實憑證（flag 例外），命中即拒。
  容器硬化：--cap-drop ALL、--security-opt no-new-privileges、--pids-limit、--memory。
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

# runner 內用 python urllib 發請求；method/url/body 以 argv 傳入，無 shell。
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
        proc.kill()
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
            path = "/" + path  # 釘在本局靶機，代理無法改打其他主機
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
            raise RuntimeError(f"docker 不可用：{err.decode(errors='replace')[:120]}")

        # G1 白名單
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(
                f"G1 拒絕：映像 {target.image!r} 不在白名單（{', '.join(self.allowlist)}）"
            )
        port = int(meta["port"])

        # G4 祕密掃描（flag 例外）
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 拒絕：環境變數 {k} 的值疑似真實憑證")

        net = f"arena-{match_id}"
        tgt = f"arena-tgt-{match_id}"
        run = f"arena-run-{match_id}"
        expires = int(time.time()) + ttl_seconds
        labels = ["--label", f"arena.match={match_id}", "--label", f"arena.expires={expires}"]
        hard = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "512m"]

        # G2 無出網網路
        rc, _, err = await _run("docker", "network", "create", "--internal", net, timeout=30)
        if rc != 0:
            raise RuntimeError(f"建立隔離網路失敗：{err.decode(errors='replace')[:160]}")

        env_args: list[str] = []
        for k, v in (target.env or {}).items():
            env_args += ["-e", f"{k}={v}"]

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", tgt, "--network", net, *labels, *hard, *env_args, target.image,
            timeout=120,
        )
        if rc != 0:
            await _run("docker", "network", "rm", net)
            raise RuntimeError(f"啟動靶機失敗：{err.decode(errors='replace')[:160]}")

        rc, _, err = await _run(
            "docker", "run", "-d", "--name", run, "--network", net, *labels, *hard,
            "python:3.12-alpine", "sleep", str(ttl_seconds),
            timeout=120,
        )
        if rc != 0:
            await _run("docker", "rm", "-f", tgt)
            await _run("docker", "network", "rm", net)
            raise RuntimeError(f"啟動 runner 失敗：{err.decode(errors='replace')[:160]}")

        sandbox = LocalDockerSandbox(net, tgt, run, f"http://{tgt}:{port}")

        # 等靶機就緒（透過 runner 輪詢）
        for _ in range(30):
            status, _body = await sandbox.http("GET", "/", timeout=8)
            if status != -1:
                break
            await asyncio.sleep(1)

        return sandbox
