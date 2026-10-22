"""Quiz 模式：一組限時題，答案可自動判。最單純、最適合當垂直切片與迴歸測試。

題目格式（mode_config.questions 的每一項）：
  id      題目識別字
  prompt  題目敘述
  answer  正解
  kind    判題方式：
            exact    （預設）正規化後整串完全相等，最嚴格
            choice   選項/單字母答案，要求 standalone token 相等（不會把 C 判進 Carbon）
            contains 正解以 token 邊界出現在答案中；ASCII 短答案自動視同 choice
            numeric  取答案最後一個數字與正解比對，容差 tol（預設 1e-6）
  tol     numeric 的容差
"""

from __future__ import annotations

import random
import re
import time
import unicodedata
from typing import Any

from ..types import Action, Event, MatchResult, Observation, Participant
from .base import Mode

# 數字 token：優先吃千分位（1,234）與小數，避免無差別去逗號破壞歐式小數/清單
_NUM_TOKEN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def _normalize(s: str) -> str:
    # NFKC 把全形數字/英文/標點轉半形，再去頭尾空白
    return unicodedata.normalize("NFKC", s or "").strip()


def _numbers(text: str) -> list[float]:
    text = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in _NUM_TOKEN.finditer(text):
        out.append(float(m.group().replace(",", "")))
    return out


def _token_match(expected: str, answer: str, ignorecase: bool) -> bool:
    # standalone token：前後不可緊鄰英數，避免 C 命中 Carbon、no 命中 Nope
    flags = re.IGNORECASE if ignorecase else 0
    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(expected) + r"(?![A-Za-z0-9])", flags)
    return bool(pat.search(answer))


def grade(question: dict[str, Any], answer: str) -> bool:
    if not (answer or "").strip():
        return False
    expected = str(question["answer"])
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
        # 大小寫敏感 token 比對：選項慣例為大寫 A/B/C/D，可避開英文冠詞 a / 代名詞 i 的假陽性
        return na.casefold() == ne.casefold() or _token_match(ne, na, ignorecase=False)

    if kind == "contains":
        if ne.isascii() and ne.isalnum():
            # ASCII 短答案（選項字母、yes/no）用 token 邊界，避免子字串假陽性
            return _token_match(ne, na, ignorecase=True)
        return ne in na  # CJK 等無詞界者用子字串；語意否定情境請改用 exact

    # exact：正規化後整串完全相等（最嚴格，不做子字串 fallback）
    return na.casefold() == ne.casefold()


class QuizMode(Mode):
    name = "quiz"

    def __init__(self, config: dict[str, Any]):
        self.questions: list[dict[str, Any]] = list(config.get("questions", []))
        self.scores: dict[str, float] = {}
        self.detail: dict[str, list[dict[str, Any]]] = {}

    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        if not self.questions:
            raise ValueError("quiz 需要至少一題")
        for i, q in enumerate(self.questions):
            if "prompt" not in q or "answer" not in q:
                raise ValueError(f"第 {i} 題缺 prompt/answer：{q!r}")
        self.scores = {p.id: 0.0 for p in participants}
        self.detail = {p.id: [] for p in participants}

    def observe(self, round_no: int, participant: Participant) -> Observation | None:
        idx = round_no - 1
        if idx >= len(self.questions):
            return None
        q = self.questions[idx]
        return Observation(
            round=round_no,
            task=q["prompt"],
            instructions="只輸出最終答案，不要解釋。",
            state={"qid": q.get("id", idx)},
        )

    async def apply(self, round_no: int, participant: Participant, action: Action) -> list[Event]:
        idx = round_no - 1
        if idx >= len(self.questions):
            return []
        q = self.questions[idx]
        correct = (action.error is None) and grade(q, action.content)
        if correct:
            self.scores[participant.id] += 1.0
        self.detail[participant.id].append(
            {
                "qid": q.get("id", idx),
                "correct": correct,
                "answer": (action.content or "")[:200],
                "error": action.error,
            }
        )
        return [
            Event(
                type="grade",
                round=round_no,
                agent=participant.id,
                data={"qid": q.get("id", idx), "correct": correct},
                ts=time.time(),
            )
        ]

    def is_done(self, round_no: int) -> bool:
        return round_no >= len(self.questions)

    def result(self) -> MatchResult:
        ranking = sorted(self.scores, key=lambda k: self.scores[k], reverse=True)
        return MatchResult(scores=dict(self.scores), ranking=ranking, details={"per_agent": self.detail})
