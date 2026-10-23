"""Mode contract: defines the tasks, legal actions and how to win. Knows nothing about any model vendor."""

from __future__ import annotations

import abc
import random
from typing import Any

from ..types import Action, Event, MatchResult, Observation, Participant

LANGS = ("zh-TW", "zh-CN", "en", "ja")
DEFAULT_LANG = "en"

# A correct answer scores 1 point, plus 0 to SPEED_BONUS_MAX for speed (the full cap at the moment the task is sent, +0 at the time limit).
# The cap is below 1: one more correct answer always beats any speed difference, so accuracy stays first and speed only separates players of similar skill.
SPEED_BONUS_MAX = 0.5


def speed_bonus(action: Any, cap: float = SPEED_BONUS_MAX) -> float:
    """Speed bonus from the time measured by the engine (meta elapsed / time_limit); no bonus if it wasn't measured. Only for correct actions."""
    elapsed, limit = action.meta.get("elapsed"), action.meta.get("time_limit")
    if cap <= 0 or not isinstance(elapsed, (int, float)) or not isinstance(limit, (int, float)) or limit <= 0:
        return 0.0
    return round(cap * max(0.0, 1.0 - elapsed / limit), 3)


def read_speed_cap(config: dict[str, Any]) -> float:
    """mode_config["speed_bonus"]: speed bonus cap, 0 disables it; must be below 1 so accuracy stays first."""
    cap = config.get("speed_bonus", SPEED_BONUS_MAX)
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not 0 <= cap < 1:
        raise ValueError(f"speed_bonus must be between 0 and 1 (1 excluded): {cap!r}")
    return float(cap)


def elapsed_seconds(action: Any) -> float | None:
    v = action.meta.get("elapsed")
    return round(v, 2) if isinstance(v, (int, float)) else None


def localize(value: Any, lang: str = DEFAULT_LANG) -> str:
    """A question field can be a string (single language) or {language: string} (multilingual); picks the given language, falling back to the default."""
    if isinstance(value, dict):
        return str(value.get(lang) or value.get(DEFAULT_LANG) or next(iter(value.values()), ""))
    return "" if value is None else str(value)


def i18n_observation(round_no: int, texts: dict[str, tuple[str, str]], state: dict[str, Any]) -> Observation:
    """texts = {language: (task, instructions)}. The Observation itself holds the default language; every language
    version goes in state["i18n"] and the connection picks one by the player's language (?lang= on remote connections)."""
    task, instructions = texts[DEFAULT_LANG]
    state = {**state, "i18n": {lang: {"task": t, "instructions": i} for lang, (t, i) in texts.items()}}
    return Observation(round=round_no, task=task, instructions=instructions, state=state)


class Mode(abc.ABC):
    name: str = "base"

    async def on_start(self, match_id: str) -> None:
        """Match start: provision resources (e.g. bring up the target for a security match). No-op by default."""

    async def on_end(self) -> None:
        """Match end: tear down resources (e.g. the target). Called whether the match ended normally or not. No-op by default."""

    @abc.abstractmethod
    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        ...

    @abc.abstractmethod
    def observe(self, round: int, participant: Participant) -> Observation | None:
        """What this agent sees this round. Returning None means the agent doesn't act this round."""

    @abc.abstractmethod
    async def apply(self, round: int, participant: Participant, action: Action) -> list[Event]:
        """Validate and score one action; return the events to write to the transcript."""

    @abc.abstractmethod
    def is_done(self, round: int) -> bool:
        ...

    @abc.abstractmethod
    def result(self) -> MatchResult:
        ...
