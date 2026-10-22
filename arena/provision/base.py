"""配置器契約：開賽拉資源、散場拆資源。把「在哪裡用什麼拉」與玩法徹底分開。"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class TargetSpec:
    image: str
    env: dict[str, str] = field(default_factory=dict)


class Sandbox(abc.ABC):
    """一個被配置出來的隔離對戰環境。引擎/模式只透過它碰靶機。"""

    @abc.abstractmethod
    async def http(self, method: str, path: str, body: str | None = None, timeout: float = 12.0) -> tuple[int, str]:
        """對靶機發 HTTP。path 被釘在本局靶機上，代理無法改打其他主機。回傳 (status, body)。"""

    @abc.abstractmethod
    async def teardown(self) -> None:
        ...


class Provisioner(abc.ABC):
    @abc.abstractmethod
    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        ...
