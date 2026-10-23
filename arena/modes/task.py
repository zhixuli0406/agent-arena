"""Task mode: everyday task matches (including document processing). Broader than quiz: tasks can carry documents/context and grading is richer.

Each task (each item of mode_config.tasks):
  id       identifier
  prompt   instruction; a string or {language: string}
  context  (optional) document/data to process, given to the agent along with the prompt; can also be a multilingual dict
  check    grading method (pick one):
    {kind: exact|choice|contains|numeric, value: ...}   reuses quiz grading
    {kind: regex, pattern: "..."}                        output must match (case-insensitive, across lines)
    {kind: contains_all, values: [...]}                  all must appear; an item can be a list = any spelling in that group is enough
    {kind: contains_any, values: [...]}                  any one must appear
    {kind: json_keys, keys: [...]}  or  {kind: json_keys, min_items: N}  output must be a JSON object with those keys / a JSON array of at least N items
    {kind: json_set, values: [...]}                      output must be a JSON array whose contents (ignoring case and order) equal values exactly
    {kind: json_fields, keys: [...], fields: {k: v}}      output must be a JSON object with keys, and the values named in fields must match (numbers may be strings)
    {kind: label, label: positive|neutral|negative}      classification: must mention the correct label (any language) and no other label
    {kind: max_words, n: N} / {kind: min_words, n: N}     word count upper/lower bound
    {kind: non_empty}                                    anything non-empty passes

Suited to everyday/document tasks: summarizing, extraction (emails/JSON), rewriting, format conversion, classification.
Open-ended scoring (needs a judge model) is planned as a separate judge mode.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from ..types import Action, Event, MatchResult, Observation, Participant
from .base import LANGS, Mode, i18n_observation, localize, read_speed_cap, elapsed_seconds, speed_bonus
from .quiz import grade as _quiz_grade

INSTRUCTIONS = {
    "zh-TW": "完成任務，只輸出結果。",
    "zh-CN": "完成任务，只输出结果。",
    "en": "Complete the task and output only the result.",
    "ja": "タスクを完了し、結果だけを出力してください。",
}
CONTEXT_HEADER = {
    "zh-TW": "--- 待處理內容 ---",
    "zh-CN": "--- 待处理内容 ---",
    "en": "--- Content to process ---",
    "ja": "--- 処理する内容 ---",
}
# label grading: how each label is written in the four languages
LABEL_WORDS = {
    "positive": ["正面", "positive", "ポジティブ"],
    "neutral": ["中性", "neutral", "中立"],
    "negative": ["負面", "负面", "negative", "ネガティブ"],
}

_JSON_RE = re.compile(r"(\{.*\}|\[.*\])", re.S)


def _extract_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    m = _JSON_RE.search(text or "")
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(1))


def _mentions(word: str, text: str) -> bool:
    if word.isascii():
        return re.search(r"(?<![a-z])" + re.escape(word.casefold()) + r"(?![a-z])", text.casefold()) is not None
    return word in text


def _same_value(got: Any, want: Any) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return float(got) == float(want)
        except (TypeError, ValueError):
            return False
    return str(got).strip().casefold() == str(want).strip().casefold()


def check_output(check: dict[str, Any], output: str) -> bool:
    kind = check.get("kind", "contains")
    out = output or ""
    if kind in ("exact", "choice", "contains", "numeric"):
        return _quiz_grade({"answer": check["value"], "kind": kind, "tol": check.get("tol", 1e-6)}, out)
    if kind == "regex":
        return re.search(check["pattern"], out, re.I | re.S) is not None
    if kind == "contains_all":
        low = out.casefold()
        return all(
            any(str(x).casefold() in low for x in v) if isinstance(v, (list, tuple)) else str(v).casefold() in low
            for v in check["values"]
        )
    if kind == "contains_any":
        low = out.casefold()
        return any(str(v).casefold() in low for v in check["values"])
    if kind == "json_keys":
        try:
            data = _extract_json(out)
        except ValueError:
            return False
        if isinstance(data, dict):
            keys = check.get("keys", [])
            # tasks that only require a count (min_items) want an array; an empty object {} must not slip through
            return bool(keys) and all(k in data for k in keys)
        if isinstance(data, list):
            keys = check.get("keys", [])
            # when keys are given, every array item must be an object with those keys (so [1] can't slip through)
            if keys and not all(isinstance(x, dict) and all(k in x for k in keys) for x in data):
                return False
            return len(data) >= int(check.get("min_items", 1))
        return False
    if kind == "json_set":
        try:
            data = _extract_json(out)
        except ValueError:
            return False
        if not isinstance(data, list):
            return False
        norm = lambda xs: {str(x).strip().casefold() for x in xs}  # noqa: E731
        return len(data) == len(norm(data)) and norm(data) == norm(check["values"])
    if kind == "json_fields":
        try:
            data = _extract_json(out)
        except ValueError:
            return False
        if not isinstance(data, dict) or not all(k in data for k in check.get("keys", [])):
            return False
        return all(_same_value(data.get(k), v) for k, v in check.get("fields", {}).items())
    if kind == "label":
        want = check["label"]
        hit = {lab for lab, words in LABEL_WORDS.items() if any(_mentions(w, out) for w in words)}
        return hit == {want}
    if kind == "max_words":
        return len(out.split()) <= int(check["n"])
    if kind == "min_words":
        return len(out.split()) >= int(check["n"])
    if kind == "non_empty":
        return bool(out.strip())
    return False


class TaskMode(Mode):
    name = "task"

    def __init__(self, config: dict[str, Any]):
        self.tasks: list[dict[str, Any]] = list(config.get("tasks", []))
        self.speed_cap = read_speed_cap(config)
        self.scores: dict[str, float] = {}
        self.detail: dict[str, list[dict[str, Any]]] = {}

    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        if not self.tasks:
            raise ValueError("task needs at least one task")
        for i, t in enumerate(self.tasks):
            if "prompt" not in t or "check" not in t:
                raise ValueError(f"task {i} is missing prompt/check: {t!r}")
        self.scores = {p.id: 0.0 for p in participants}
        self.detail = {p.id: [] for p in participants}

    def observe(self, round_no: int, participant: Participant) -> Observation | None:
        idx = round_no - 1
        if idx >= len(self.tasks):
            return None
        t = self.tasks[idx]
        texts: dict[str, tuple[str, str]] = {}
        for lang in LANGS:
            task_text = localize(t["prompt"], lang)
            if t.get("context"):
                task_text += f"\n\n{CONTEXT_HEADER[lang]}\n" + localize(t["context"], lang)
            texts[lang] = (task_text, INSTRUCTIONS[lang])
        return i18n_observation(round_no, texts, {"id": t.get("id", idx)})

    async def apply(self, round_no: int, participant: Participant, action: Action) -> list[Event]:
        idx = round_no - 1
        if idx >= len(self.tasks):
            return []
        t = self.tasks[idx]
        ok = (action.error is None) and check_output(t["check"], action.content)
        points = round(1.0 + speed_bonus(action, self.speed_cap), 3) if ok else 0.0
        self.scores[participant.id] = round(self.scores[participant.id] + points, 3)
        seconds = elapsed_seconds(action)
        self.detail[participant.id].append(
            {"id": t.get("id", idx), "ok": ok, "points": points, "seconds": seconds,
             "output": (action.content or "")[:200], "error": action.error}
        )
        return [Event(type="grade", round=round_no, agent=participant.id,
                      data={"id": t.get("id", idx), "ok": ok, "points": points, "seconds": seconds}, ts=time.time())]

    def is_done(self, round_no: int) -> bool:
        return round_no >= len(self.tasks)

    def result(self) -> MatchResult:
        ranking = sorted(self.scores, key=lambda k: self.scores[k], reverse=True)
        return MatchResult(scores=dict(self.scores), ranking=ranking, details={"per_agent": self.detail})
