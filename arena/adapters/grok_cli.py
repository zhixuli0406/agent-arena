"""xAI/Grok adapter：呼叫本機 grok headless（`grok --prompt-file ... --output-format plain`）。

用 grok 自己的登入，不需另發金鑰。prompt 寫進暫存檔以 --prompt-file 餵入（避開選項注入）；
plain 輸出即最終答案。is_host_actor=True：grok 在宿主機帶工具，資安場預設禁用（C1）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time

from ..security import validate_model_name
from ..types import Action, Observation, Usage
from .base import Adapter, AdapterUnavailable, render_observation


class GrokCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("grok") is None:
            raise AdapterUnavailable("找不到 grok CLI")
        validate_model_name(self.spec.model)
        prompt = render_observation(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"

        fd, ppath = tempfile.mkstemp(prefix="arena_grok_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        cmd = ["grok", "--prompt-file", ppath, "--output-format", "plain",
               "--always-approve", "--disable-web-search"]
        if self.spec.model:
            cmd += ["-m", self.spec.model]

        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True
        )
        try:
            out, err = await proc.communicate()
        except asyncio.CancelledError:
            self._kill(proc)
            raise
        finally:
            if proc.returncode is None:
                self._kill(proc)
            try:
                os.unlink(ppath)
            except OSError:
                pass

        content = out.decode(errors="replace").strip()
        if not content and proc.returncode != 0:
            raise AdapterUnavailable(f"grok 結束碼 {proc.returncode}: {err.decode(errors='replace')[:200]}")
        return Action(content=content, usage=Usage(wall_seconds=time.monotonic() - t0))

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
