"""Mode 契約：定義任務、合法動作、怎麼算贏。不懂任何一家模型。"""

from __future__ import annotations

import abc
import random

from ..types import Action, Event, MatchResult, Observation, Participant


class Mode(abc.ABC):
    name: str = "base"

    async def on_start(self, match_id: str) -> None:
        """開賽：配置資源（如資安場拉起靶機）。預設 no-op。"""

    async def on_end(self) -> None:
        """散場：拆除資源（如拆靶機）。無論對戰正常或異常結束都會被呼叫。預設 no-op。"""

    @abc.abstractmethod
    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        ...

    @abc.abstractmethod
    def observe(self, round: int, participant: Participant) -> Observation | None:
        """這一回合這位代理看到什麼。回傳 None 表示本回合這位代理不出手。"""

    @abc.abstractmethod
    async def apply(self, round: int, participant: Participant, action: Action) -> list[Event]:
        """驗證並結算一個動作，回傳要留痕的事件。"""

    @abc.abstractmethod
    def is_done(self, round: int) -> bool:
        ...

    @abc.abstractmethod
    def result(self) -> MatchResult:
        ...
