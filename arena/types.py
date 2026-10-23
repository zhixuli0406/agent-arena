"""Core data structures. Components talk to each other only through these types, never through implicit shared state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    """Resource usage of one adapter action. Read by both scoring and the circuit breaker."""

    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    cost_usd: float = 0.0


@dataclass
class Observation:
    """What an agent sees this round."""

    round: int
    task: str
    instructions: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Action:
    """What an agent does this step. The mode interprets content."""

    content: str = ""
    usage: Usage = field(default_factory=Usage)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> str | None:
        return self.meta.get("error")


@dataclass
class AgentSpec:
    """Configuration of one competing agent. system_prompt is what the human operator tunes."""

    id: str
    adapter: str
    model: str = ""
    system_prompt: str = ""
    prompt_author: str = "anon"
    team: str = ""  # For team matches; empty = free-for-all (each agent is its own team). Participants are already a list, so N-player matches work.
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Participant:
    """A runtime participant: binds a spec to its adapter instance."""

    spec: AgentSpec
    adapter: Any = None  # adapters.base.Adapter

    @property
    def id(self) -> str:
        return self.spec.id


@dataclass
class Event:
    """One line of the transcript. The single source of truth."""

    type: str
    round: int
    agent: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


@dataclass
class MatchResult:
    scores: dict[str, float]
    ranking: list[str]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchConfig:
    mode: str
    agents: list[AgentSpec]
    mode_config: dict[str, Any] = field(default_factory=dict)
    max_rounds: int = 100
    max_wall_seconds: float = 600.0
    timeout_seconds: float = 60.0
    seed: int = 0
    ratings_path: str = "ratings.json"
    # Whether to update the team ladder (keyed by team name). Only meaningful for fixed-name team matches;
    # the lobby's random red/blue split has different people every match, so recording under one team name is just noise.
    team_ladder: bool = True

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MatchConfig":
        agents = []
        for a in d.get("agents", []):
            agents.append(
                AgentSpec(
                    id=a["id"],
                    adapter=a["adapter"],
                    model=a.get("model", ""),
                    system_prompt=a.get("system_prompt", ""),
                    prompt_author=a.get("prompt_author", "anon"),
                    team=a.get("team", ""),
                    params=a.get("params", {}),
                )
            )
        if not agents:
            raise ValueError("agents must not be empty")
        ids = [a.id for a in agents]
        if len(set(ids)) != len(ids):
            raise ValueError(f"agent ids must be unique, found duplicates: {ids}")
        return MatchConfig(
            mode=d["mode"],
            agents=agents,
            mode_config=d.get("mode_config", {}),
            max_rounds=d.get("max_rounds", 100),
            max_wall_seconds=d.get("max_wall_seconds", 600.0),
            timeout_seconds=d.get("timeout_seconds", 60.0),
            seed=d.get("seed", 0),
            ratings_path=d.get("ratings_path", "ratings.json"),
            team_ladder=bool(d.get("team_ladder", True)),
        )
