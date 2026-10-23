"""Mode registry and factory. Adding a game mode = registering a mode here; the engine stays untouched."""

from __future__ import annotations

from typing import Any

from .base import Mode
from .ctf import CTFMode
from .quiz import QuizMode
from .task import TaskMode

REGISTRY: dict[str, type[Mode]] = {
    "quiz": QuizMode,
    "ctf": CTFMode,
    "task": TaskMode,
}


def build_mode(name: str, config: dict[str, Any]) -> Mode:
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown match mode: {name} (available: {', '.join(REGISTRY)})")
    return cls(config)


__all__ = ["Mode", "build_mode", "REGISTRY"]
