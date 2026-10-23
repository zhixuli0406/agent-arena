"""xAI/Grok adapter: calls the local headless grok (`grok --prompt-file ... --output-format plain`).

Uses grok's own login, no separate key needed. The prompt is written to a temp file and fed via --prompt-file
(avoids option injection); the plain output is the final answer. is_host_actor=True: grok runs with tools on the
host, disabled by default in security matches (C1).

Security (only available on private servers with ARENA_ALLOW_HOST_ADAPTERS=1; the task/history is untrusted content for it):
- No --always-approve; uses --permission-mode dontAsk instead (any tool that needs approval is refused).
- The tool allowlist keeps only web_search, which --disable-web-search then removes -> effectively no tools;
  --disallowed-tools also explicitly removes file read/write, shell, monitor, subagents, MCP meta tools and web_fetch.
  (Tested: grok's `--tools ""` has no effect, and a denylist alone is bypassed via monitor, so both are used.)
- --sandbox strict: the OS layer (macOS Seatbelt / Linux Landlock) restricts reads to cwd and required system paths.
- cwd is a fresh empty temp dir per call, deleted afterwards; the prompt file lives there too.
- The task and history are wrapped in a wrap_untrusted fence (the engine's answer instructions stay outside), stating that instructions inside must not be followed.
Residual risk: grok still loads user-level settings (~/.grok, global instructions); on macOS, strict doesn't block child processes from reaching the network.
For stronger isolation run it in a container, or don't enable host adapters on machines with sensitive data.
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

# the allowlist holds a single tool that --disable-web-search then removes = no tools available
_GROK_TOOLS = "web_search"
_GROK_DENIED = (
    "read_file,grep,list_dir,search_replace,write,Delete,run_terminal_cmd,"
    "monitor,task,use_tool,search_tool,web_fetch"
)


def build_grok_cmd(prompt_path: str, cwd: str, model: str = "") -> list[str]:
    cmd = [
        "grok", "--prompt-file", prompt_path, "--output-format", "plain",
        "--cwd", cwd, "--sandbox", "strict", "--permission-mode", "dontAsk",
        "--tools", _GROK_TOOLS, "--disallowed-tools", _GROK_DENIED,
        "--disable-web-search", "--no-subagents",
    ]
    if model:
        cmd += ["-m", model]
    return cmd


class GrokCLIAdapter(Adapter):
    is_host_actor = True

    async def act(self, obs: Observation) -> Action:
        if shutil.which("grok") is None:
            raise AdapterUnavailable("grok CLI not found")
        validate_model_name(self.spec.model)
        prompt = render_observation_fenced(obs)
        if self.spec.system_prompt:
            prompt = f"{self.spec.system_prompt}\n\n{prompt}"

        workdir = tempfile.mkdtemp(prefix="arena_grok_")
        ppath = os.path.join(workdir, "prompt.txt")
        with open(ppath, "w", encoding="utf-8") as f:
            f.write(prompt)
        cmd = build_grok_cmd(ppath, workdir, self.spec.model)

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=workdir, start_new_session=True,
            )
            try:
                out, err = await proc.communicate()
            except asyncio.CancelledError:
                self._kill(proc)
                raise
            finally:
                self._kill(proc)  # on timeout/cancel kill the whole group; on normal exit also clean up leftover grandchildren (MCP, background shells)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        content = out.decode(errors="replace").strip()
        if not content and proc.returncode != 0:
            raise AgentFailed(f"grok exit code {proc.returncode}: {err.decode(errors='replace')[:200]}")
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
