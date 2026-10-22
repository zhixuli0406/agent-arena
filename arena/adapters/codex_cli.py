"""OpenAI/Codex adapter：呼叫本機 codex exec（非互動）。用 codex 自己的登入，不需另發金鑰。

- 這是真正的跨廠商對手（OpenAI）：與 claude_cli 同為「本機 CLI、各自登入」路線。
- prompt 走 stdin（`codex exec -o FILE -`），不進 argv，避免選項注入。
- 最終答案由 `-o <file>`（output-last-message）取回，避開 codex 的冗長日誌。
- is_host_actor=True：codex exec 在宿主機帶工具，資安場預設禁用（同 C1 關卡）。
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


class CodexCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("codex") is None:
            raise AdapterUnavailable("找不到 codex CLI")
        validate_model_name(self.spec.model)
        prompt = render_observation(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"

        fd, outpath = tempfile.mkstemp(prefix="arena_codex_", suffix=".txt")
        os.close(fd)
        cmd = ["codex", "exec", "-o", outpath]
        if self.spec.model:
            cmd += ["-m", self.spec.model]
        cmd.append("-")  # 從 stdin 讀 prompt

        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        try:
            await proc.communicate(prompt.encode())
        except asyncio.CancelledError:
            self._kill(proc)
            raise
        finally:
            if proc.returncode is None:
                self._kill(proc)

        content = ""
        try:
            with open(outpath, encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            pass
        finally:
            try:
                os.unlink(outpath)
            except OSError:
                pass

        if not content and proc.returncode != 0:
            raise AdapterUnavailable(f"codex 結束碼 {proc.returncode}（無輸出）")
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
