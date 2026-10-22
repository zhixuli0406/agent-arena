"""Adapter 契約：廠商中立的 act(observation) -> action。"""

from __future__ import annotations

import abc

from ..types import Action, AgentSpec, Observation


class AdapterUnavailable(RuntimeError):
    """adapter 無法服務（工具缺失、金鑰未設、端點不可達）。引擎據此如實降級標記。"""


class Adapter(abc.ABC):
    # 這個 adapter 的代理是否跑在宿主機、具自有工具與出網能力（如 claude -p）。
    # 資安場（ctf）預設禁用這類 adapter：攻擊方必須在沙箱內，引擎是唯一致動者。
    is_host_actor: bool = False

    def __init__(self, spec: AgentSpec):
        self.spec = spec

    @abc.abstractmethod
    async def act(self, obs: Observation) -> Action:
        ...


def render_observation(obs: Observation) -> str:
    """把 Observation 渲染成給模型的使用者訊息。system prompt 由各 adapter 另外處理。"""
    lines = [f"# 回合 {obs.round}"]
    if obs.instructions:
        lines.append(obs.instructions)
    lines.append("")
    lines.append(obs.task)
    if obs.history:
        lines.append("")
        lines.append("## 歷史")
        for h in obs.history[-5:]:
            lines.append(f"- {h}")
    return "\n".join(lines)
