"""Claude adapter: calls the local headless claude -p. It uses the local login, so it can be a real opponent without issuing a separate key.

Security:
- is_host_actor=True: this is a host-side agentic CLI, disabled by default in security matches (see the C1 gate in modes/ctf.py).
- The prompt goes through stdin, not argv, so untrusted content can't be parsed as CLI options (option injection).
- On timeout/cancel the child processes are killed by process group, so orphans don't keep burning tokens.
- The task and history are untrusted: they are wrapped in a wrap_untrusted fence (answer instructions stay outside);
  `--tools ""` turns off every built-in tool, `--strict-mcp-config` loads no MCP, `--setting-sources ""` applies no
  user/project settings (so the host's permission allow rules aren't inherited); cwd is a fresh empty temp dir per call, deleted afterwards.
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
from .base import Adapter, AdapterUnavailable, AgentFailed, render_observation_fenced


def build_claude_cmd(model: str = "") -> list[str]:
    cmd = ["claude", "-p", "--tools", "", "--strict-mcp-config", "--setting-sources", ""]
    if model:
        cmd += ["--model", model]
    return cmd


class ClaudeCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("claude") is None:
            raise AdapterUnavailable("claude CLI not found")
        validate_model_name(self.spec.model)
        prompt = render_observation_fenced(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"
        cmd = build_claude_cmd(self.spec.model)

        t0 = time.monotonic()
        workdir = tempfile.mkdtemp(prefix="arena_claude_")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                start_new_session=True,  # own process group so the whole group can be reaped
            )
            try:
                out, err = await proc.communicate(prompt.encode())
            except asyncio.CancelledError:
                self._kill(proc)
                raise
            finally:
                self._kill(proc)  # on timeout/cancel kill the whole group; on normal exit also clean up leftover grandchildren (MCP, background shells)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        if proc.returncode != 0:
            raise AgentFailed(f"claude exit code {proc.returncode}: {err.decode(errors='replace')[:200]}")
        return Action(content=out.decode(errors="replace").strip(), usage=Usage(wall_seconds=time.monotonic() - t0))

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        # start_new_session=True → pgid == pid; the group may still have leftover members after the leader exits
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
