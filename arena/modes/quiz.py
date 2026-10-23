"""Quiz mode: a set of timed questions with automatically graded answers. The simplest mode, best suited as a vertical slice and for regression tests.

Question format (each item of mode_config.questions):
  id      question identifier
  prompt  question text; a string or {language: string} (zh-TW / zh-CN / en / ja)
  answer  correct answer; may be a list (any match counts, e.g. multilingual "星期一 / Monday")
  kind    grading method:
            exact    (default) whole string equal after normalization; the strictest
            choice   option/single-letter answers; requires an equal standalone token (C won't match Carbon)
            contains the correct answer appears in the reply on token boundaries; short ASCII answers are treated as choice
            numeric  compares the last number in the reply with the answer, tolerance tol (default 1e-6)
  tol     tolerance for numeric
  distractors (optional) spellings of the other options; mentioning any of them is graded wrong (stops "list every option")
"""

from __future__ import annotations

import random
import re
import time
import unicodedata
from typing import Any

from ..types import Action, Event, MatchResult, Observation, Participant
from .base import LANGS, Mode, i18n_observation, localize, read_speed_cap, elapsed_seconds, speed_bonus

INSTRUCTIONS = {
    "zh-TW": "只輸出最終答案，不要解釋。",
    "zh-CN": "只输出最终答案，不要解释。",
    "en": "Output only the final answer, with no explanation.",
    "ja": "最終的な答えだけを出力し、説明はしないでください。",
}

# Number token: match thousands separators (1,234) and decimals first, so blindly stripping commas can't break European decimals/lists
_NUM_TOKEN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def _normalize(s: str) -> str:
    # NFKC turns full-width digits/letters/punctuation into half-width, then strip surrounding whitespace
    return unicodedata.normalize("NFKC", s or "").strip()


def _numbers(text: str) -> list[float]:
    text = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in _NUM_TOKEN.finditer(text):
        out.append(float(m.group().replace(",", "")))
    return out


def _token_match(expected: str, answer: str, ignorecase: bool) -> bool:
    # standalone token: no adjacent letters/digits on either side, so C doesn't hit Carbon and no doesn't hit Nope
    flags = re.IGNORECASE if ignorecase else 0
    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(expected) + r"(?![A-Za-z0-9])", flags)
    return bool(pat.search(answer))


_LONE_CAPITAL = re.compile(r"(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])")


def _mentions(word: str, text: str) -> bool:
    if word.isascii():
        return _token_match(word, text, ignorecase=True)
    return word in text


def grade(question: dict[str, Any], answer: str) -> bool:
    if not (answer or "").strip():
        return False
    na_all = _normalize(answer)
    if any(_mentions(_normalize(str(d)), na_all) for d in question.get("distractors", [])):
        return False                       # also mentions other options: listing everything can't guess its way to a correct answer
    expected_any = question["answer"]
    if isinstance(expected_any, (list, tuple)):
        return any(grade({**question, "answer": e}, answer) for e in expected_any)
    expected = str(expected_any)
    kind = question.get("kind", "exact")
    na, ne = _normalize(answer), _normalize(expected)

    if kind == "numeric":
        nums = _numbers(answer)
        if not nums:
            return False
        try:
            exp = float(ne.replace(",", ""))
        except ValueError:
            return False
        return abs(nums[-1] - exp) <= float(question.get("tol", 1e-6))

    if kind == "choice":
        # case-sensitive token match: options are conventionally uppercase A/B/C/D, which avoids false positives from the article a / pronoun i
        if na.casefold() == ne.casefold():
            return True
        # single uppercase letter option: the reply may contain only one standalone capital letter (listing "A B C D" doesn't count)
        if len(ne) == 1 and ne.isupper() and len(set(_LONE_CAPITAL.findall(na))) > 1:
            return False
        return _token_match(ne, na, ignorecase=False)

    if kind == "contains":
        if ne.isascii() and ne.isalnum():
            # short ASCII answers (option letters, yes/no) use token boundaries to avoid substring false positives
            return _token_match(ne, na, ignorecase=True)
        return ne in na  # CJK and other scripts without word boundaries use substring match; use exact where negation matters

    # exact: whole string equal after normalization (strictest, no substring fallback)
    return na.casefold() == ne.casefold()


class QuizMode(Mode):
    name = "quiz"

    def __init__(self, config: dict[str, Any]):
        self.questions: list[dict[str, Any]] = list(config.get("questions", []))
        self.speed_cap = read_speed_cap(config)
        self.scores: dict[str, float] = {}
        self.detail: dict[str, list[dict[str, Any]]] = {}

    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        if not self.questions:
            raise ValueError("quiz needs at least one question")
        for i, q in enumerate(self.questions):
            if "prompt" not in q or "answer" not in q:
                raise ValueError(f"question {i} is missing prompt/answer: {q!r}")
        self.scores = {p.id: 0.0 for p in participants}
        self.detail = {p.id: [] for p in participants}

    def observe(self, round_no: int, participant: Participant) -> Observation | None:
        idx = round_no - 1
        if idx >= len(self.questions):
            return None
        q = self.questions[idx]
        texts = {lang: (localize(q["prompt"], lang), INSTRUCTIONS[lang]) for lang in LANGS}
        return i18n_observation(round_no, texts, {"qid": q.get("id", idx)})

    async def apply(self, round_no: int, participant: Participant, action: Action) -> list[Event]:
        idx = round_no - 1
        if idx >= len(self.questions):
            return []
        q = self.questions[idx]
        correct = (action.error is None) and grade(q, action.content)
        bonus = speed_bonus(action, self.speed_cap) if correct else 0.0
        points = round(1.0 + bonus, 3) if correct else 0.0
        self.scores[participant.id] = round(self.scores[participant.id] + points, 3)
        seconds = elapsed_seconds(action)
        self.detail[participant.id].append(
            {
                "qid": q.get("id", idx),
                "correct": correct,
                "points": points,
                "seconds": seconds,
                "answer": (action.content or "")[:200],
                "error": action.error,
            }
        )
        return [
            Event(
                type="grade",
                round=round_no,
                agent=participant.id,
                data={"qid": q.get("id", idx), "correct": correct, "points": points, "seconds": seconds},
                ts=time.time(),
            )
        ]

    def is_done(self, round_no: int) -> bool:
        return round_no >= len(self.questions)

    def result(self) -> MatchResult:
        ranking = sorted(self.scores, key=lambda k: self.scores[k], reverse=True)
        return MatchResult(scores=dict(self.scores), ranking=ranking, details={"per_agent": self.detail})
