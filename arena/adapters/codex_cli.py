"""OpenAI/Codex adapter: calls the local codex exec (non-interactive). Uses codex's own login, no separate key needed.

- This is a real cross-vendor opponent (OpenAI), on the same "local CLI, own login" path as claude_cli.
- The prompt goes through stdin (`codex exec -o FILE -`), not argv, to avoid option injection.
- The final answer is read from `-o <file>` (output-last-message), skipping codex's verbose logs.
- is_host_actor=True: codex exec runs with tools on the host, disabled by default in security matches (same C1 gate).
- The task and history are untrusted: they are wrapped in a wrap_untrusted fence (answer instructions stay outside);
  `--sandbox read-only` blocks file writes and network access, `--ephemeral` saves no session;
  `--ignore-user-config` skips ~/.codex/config.toml (its MCP/plugins run outside the sandbox); cwd (-C) is a fresh empty temp dir per call, deleted afterwards.
  Residual risk: the read-only sandbox can still read host files, so don't enable host adapters on machines with sensitive data.
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


def build_codex_cmd(outpath: str, workdir: str, model: str = "") -> list[str]:
    cmd = ["codex", "exec", "--ignore-user-config", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
           "-C", workdir, "-o", outpath]
    if model:
        cmd += ["-m", model]
    cmd.append("-")  # read the prompt from stdin
    return cmd


class CodexCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("codex") is None:
            raise AdapterUnavailable("codex CLI not found")
        validate_model_name(self.spec.model)
        prompt = render_observation_fenced(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"

        workdir = tempfile.mkdtemp(prefix="arena_codex_")
        outpath = os.path.join(workdir, "last_message.txt")
        cmd = build_codex_cmd(outpath, workdir, self.spec.model)

        t0 = time.monotonic()
        content = ""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=workdir, start_new_session=True,
            )
            try:
                await proc.communicate(prompt.encode())
            except asyncio.CancelledError:
                self._kill(proc)
                raise
            finally:
                self._kill(proc)  # on timeout/cancel kill the whole group; on normal exit also clean up leftover grandchildren (MCP, background shells)
            try:
                with open(outpath, encoding="utf-8") as f:
                    content = f.read().strip()
            except OSError:
                pass
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        if not content and proc.returncode != 0:
            raise AgentFailed(f"codex exit code {proc.returncode} (no output)")
        return Action(content=content, usage=Usage(wall_seconds=time.monotonic() - t0))

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
