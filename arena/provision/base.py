"""Provisioner contract: bring resources up at match start, tear them down at match end. Keeps "where and with what" fully separate from the game mode."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class TargetSpec:
    image: str
    env: dict[str, str] = field(default_factory=dict)


class Sandbox(abc.ABC):
    """A provisioned, isolated match environment. The engine/mode only touch the target through it."""

    @abc.abstractmethod
    async def http(self, method: str, path: str, body: str | None = None, timeout: float = 12.0) -> tuple[int, str]:
        """Send HTTP to the target. path is pinned to this match's target, so agents can't hit other hosts. Returns (status, body)."""

    @abc.abstractmethod
    async def teardown(self) -> None:
        ...


class Provisioner(abc.ABC):
    @abc.abstractmethod
    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        ...
