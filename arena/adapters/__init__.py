"""Adapter registry and factory. Adding a vendor = registering an adapter here; the engine stays untouched."""

from __future__ import annotations

from ..types import AgentSpec
from .base import Adapter, AdapterUnavailable
from .claude_cli import ClaudeCLIAdapter
from .codex_cli import CodexCLIAdapter
from .grok_cli import GrokCLIAdapter
from .mock import MockAdapter
from .openai_compat import OpenAICompatAdapter
from .remote import RemoteAdapter

REGISTRY: dict[str, type[Adapter]] = {
    "mock": MockAdapter,
    "claude_cli": ClaudeCLIAdapter,
    "codex_cli": CodexCLIAdapter,
    "grok_cli": GrokCLIAdapter,
    "openai_compat": OpenAICompatAdapter,
    "remote": RemoteAdapter,  # player-supplied agents through one shared entry point (zero owner keys)
}


def build_adapter(spec: AgentSpec) -> Adapter:
    cls = REGISTRY.get(spec.adapter)
    if cls is None:
        raise ValueError(f"unknown adapter: {spec.adapter} (available: {', '.join(REGISTRY)})")
    return cls(spec)


__all__ = ["Adapter", "AdapterUnavailable", "build_adapter", "REGISTRY"]
