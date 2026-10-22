"""Adapter 註冊表與工廠。加入新廠商＝在此註冊一個 adapter，引擎不動。"""

from __future__ import annotations

from ..types import AgentSpec
from .base import Adapter, AdapterUnavailable
from .claude_cli import ClaudeCLIAdapter
from .codex_cli import CodexCLIAdapter
from .grok_cli import GrokCLIAdapter
from .mock import MockAdapter
from .openai_compat import OpenAICompatAdapter

REGISTRY: dict[str, type[Adapter]] = {
    "mock": MockAdapter,
    "claude_cli": ClaudeCLIAdapter,
    "codex_cli": CodexCLIAdapter,
    "grok_cli": GrokCLIAdapter,
    "openai_compat": OpenAICompatAdapter,
}


def build_adapter(spec: AgentSpec) -> Adapter:
    cls = REGISTRY.get(spec.adapter)
    if cls is None:
        raise ValueError(f"未知 adapter：{spec.adapter}（可用：{', '.join(REGISTRY)}）")
    return cls(spec)


__all__ = ["Adapter", "AdapterUnavailable", "build_adapter", "REGISTRY"]
