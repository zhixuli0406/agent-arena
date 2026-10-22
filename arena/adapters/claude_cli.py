"""Claude adapter：呼叫本機 claude -p headless。拿本機登入態就能當真對手，不需另發金鑰。

安全：
- is_host_actor=True：這是宿主側 agentic CLI，資安場預設禁用（見 modes/ctf.py 的 C1 關卡）。
- prompt 走 stdin，不進 argv，避免不可信內容被當成 CLI 選項解析（選項注入）。
- 逾時/取消時以 process group 強殺子行程，避免孤兒進程繼續燒 token。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time

from ..security import validate_model_name
from ..types import Action, Observation, Usage
from .base import Adapter, AdapterUnavailable, render_observation


class ClaudeCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("claude") is None:
            raise AdapterUnavailable("找不到 claude CLI")
        validate_model_name(self.spec.model)
        prompt = render_observation(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"
        cmd = ["claude", "-p"]
        if self.spec.model:
            cmd += ["--model", self.spec.model]

        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # 自成 process group，便於整組回收
        )
        try:
            out, err = await proc.communicate(prompt.encode())
        except asyncio.CancelledError:
            self._kill(proc)
            raise
        finally:
            if proc.returncode is None:
                self._kill(proc)

        if proc.returncode != 0:
            raise AdapterUnavailable(f"claude 結束碼 {proc.returncode}: {err.decode(errors='replace')[:200]}")
        return Action(content=out.decode(errors="replace").strip(), usage=Usage(wall_seconds=time.monotonic() - t0))

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
