"""Mode 註冊表與工廠。加入新玩法＝在此註冊一個 mode，引擎不動。"""

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
        raise ValueError(f"未知對戰模式：{name}（可用：{', '.join(REGISTRY)}）")
    return cls(config)


__all__ = ["Mode", "build_mode", "REGISTRY"]
