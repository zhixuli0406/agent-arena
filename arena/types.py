"""核心資料結構。跨元件溝通只靠這些型別，不走隱式共享狀態。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    """一次 adapter 動作的耗用。計分與斷路器都要讀。"""

    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    cost_usd: float = 0.0


@dataclass
class Observation:
    """代理這一回合看到的東西。"""

    round: int
    task: str
    instructions: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Action:
    """代理這一步要做的事。mode 負責詮釋 content。"""

    content: str = ""
    usage: Usage = field(default_factory=Usage)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> str | None:
        return self.meta.get("error")


@dataclass
class AgentSpec:
    """一位參賽代理的設定。system_prompt 就是人類操盤手要調的東西。"""

    id: str
    adapter: str
    model: str = ""
    system_prompt: str = ""
    prompt_author: str = "anon"
    team: str = ""  # 組隊對戰用；空＝自由對戰（每個代理自成一隊）。引擎參賽者本為 list，N 人對戰已支援。
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Participant:
    """執行期的參賽者：綁定 spec 與其 adapter 實例。"""

    spec: AgentSpec
    adapter: Any = None  # adapters.base.Adapter

    @property
    def id(self) -> str:
        return self.spec.id


@dataclass
class Event:
    """transcript 的一行。唯一真相來源。"""

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
            raise ValueError("agents 不可為空")
        ids = [a.id for a in agents]
        if len(set(ids)) != len(ids):
            raise ValueError(f"agent id 必須唯一，出現重複：{ids}")
        return MatchConfig(
            mode=d["mode"],
            agents=agents,
            mode_config=d.get("mode_config", {}),
            max_rounds=d.get("max_rounds", 100),
            max_wall_seconds=d.get("max_wall_seconds", 600.0),
            timeout_seconds=d.get("timeout_seconds", 60.0),
            seed=d.get("seed", 0),
            ratings_path=d.get("ratings_path", "ratings.json"),
        )
