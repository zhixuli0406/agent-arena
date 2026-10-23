"""Adapter contract: a vendor-neutral act(observation) -> action."""

from __future__ import annotations

import abc

from ..security import wrap_untrusted
from ..types import Action, AgentSpec, Observation


class AdapterUnavailable(RuntimeError):
    """The adapter can't serve (missing tool, unset key, unreachable endpoint). The engine uses this to mark the match as degraded."""


class AgentFailed(RuntimeError):
    """The agent process started but failed (non-zero exit code and no output). Attributed to the participant:
    that round is a forfeit and the match is still scored.

    Kept separate from AdapterUnavailable because "CLI not found" is an environment problem, while "CLI ran but
    crashed" may be a prompt that made the model refuse or the agent itself crashing; counting it as an
    infrastructure failure would give a loser a way to void the match.
    """


class Adapter(abc.ABC):
    # Whether this adapter's agent runs on the host with its own tools and network access (e.g. claude -p).
    # Security matches (ctf) disable these adapters by default: the attacker must be sandboxed and the engine is the only actor.
    is_host_actor: bool = False

    def __init__(self, spec: AgentSpec):
        self.spec = spec

    @abc.abstractmethod
    async def act(self, obs: Observation) -> Action:
        ...


def render_observation(obs: Observation) -> str:
    """Render an Observation as the user message for the model. Each adapter handles the system prompt separately."""
    lines = [f"# Round {obs.round}"]
    if obs.instructions:
        lines.append(obs.instructions)
    lines.append("")
    lines.append(obs.task)
    if obs.history:
        lines.append("")
        lines.append("## History")
        for h in obs.history[-5:]:
            lines.append(f"- {h}")
    return "\n".join(lines)


def render_observation_fenced(obs: Observation, source: str = "arena question") -> str:
    """For host-side agentic CLIs: the engine's own answer instructions stay outside the fence, while the task and
    history (which may contain external content such as target responses) go inside a wrap_untrusted fence."""
    lines = [f"# Round {obs.round}"]
    if obs.instructions:
        lines.append(obs.instructions)
    body = [obs.task]
    if obs.history:
        body.append("")
        body.append("## History")
        for h in obs.history[-5:]:
            body.append(f"- {h}")
    lines.append("")
    lines.append(wrap_untrusted("\n".join(body), source=source))
    return "\n".join(lines)
