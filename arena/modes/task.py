"""Task 模式：日常任務對戰（含文件處理）。比 quiz 廣——題目可帶文件/情境，判分更豐富。

每題（mode_config.tasks 的每一項）：
  id       識別字
  prompt   指令
  context  （可選）要處理的文件/資料，會一起給代理
  check    判分方式（擇一）：
    {kind: exact|choice|contains|numeric, value: ...}   沿用 quiz 判題
    {kind: regex, pattern: "..."}                        輸出需 match（忽略大小寫、跨行）
    {kind: contains_all, values: [...]}                  需全部出現
    {kind: contains_any, values: [...]}                  需任一出現
    {kind: json_keys, keys: [...]}  或  {kind: json_keys, min_items: N}  輸出需為含該些鍵的 JSON 物件／至少 N 筆的 JSON 陣列
    {kind: max_words, n: N} / {kind: min_words, n: N}     字數上/下限
    {kind: non_empty}                                    非空即可

適合：摘要、抽取（emails/JSON）、改寫、格式轉換、分類等日常/文件任務。開放式評分（需裁判模型）見 judge 模式（規劃中）。
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from ..types import Action, Event, MatchResult, Observation, Participant
from .base import Mode
from .quiz import grade as _quiz_grade

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


def check_output(check: dict[str, Any], output: str) -> bool:
    kind = check.get("kind", "contains")
    out = output or ""
    if kind in ("exact", "choice", "contains", "numeric"):
        return _quiz_grade({"answer": check["value"], "kind": kind, "tol": check.get("tol", 1e-6)}, out)
    if kind == "regex":
        return re.search(check["pattern"], out, re.I | re.S) is not None
    if kind == "contains_all":
        low = out.casefold()
        return all(str(v).casefold() in low for v in check["values"])
    if kind == "contains_any":
        low = out.casefold()
        return any(str(v).casefold() in low for v in check["values"])
    if kind == "json_keys":
        try:
            data = _extract_json(out)
        except ValueError:
            return False
        if isinstance(data, dict):
            return all(k in data for k in check.get("keys", []))
        if isinstance(data, list):
            return len(data) >= int(check.get("min_items", 1))
        return False
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
        self.scores: dict[str, float] = {}
        self.detail: dict[str, list[dict[str, Any]]] = {}

    def setup(self, participants: list[Participant], rng: random.Random) -> None:
        if not self.tasks:
            raise ValueError("task 需要至少一題")
        for i, t in enumerate(self.tasks):
            if "prompt" not in t or "check" not in t:
                raise ValueError(f"第 {i} 題缺 prompt/check：{t!r}")
        self.scores = {p.id: 0.0 for p in participants}
        self.detail = {p.id: [] for p in participants}

    def observe(self, round_no: int, participant: Participant) -> Observation | None:
        idx = round_no - 1
        if idx >= len(self.tasks):
            return None
        t = self.tasks[idx]
        task_text = t["prompt"]
        if t.get("context"):
            task_text += "\n\n--- 待處理內容 ---\n" + str(t["context"])
        return Observation(round=round_no, task=task_text, instructions="完成任務，只輸出結果。", state={"id": t.get("id", idx)})

    async def apply(self, round_no: int, participant: Participant, action: Action) -> list[Event]:
        idx = round_no - 1
        if idx >= len(self.tasks):
            return []
        t = self.tasks[idx]
        ok = (action.error is None) and check_output(t["check"], action.content)
        if ok:
            self.scores[participant.id] += 1.0
        self.detail[participant.id].append(
            {"id": t.get("id", idx), "ok": ok, "output": (action.content or "")[:200], "error": action.error}
        )
        return [Event(type="grade", round=round_no, agent=participant.id, data={"id": t.get("id", idx), "ok": ok}, ts=time.time())]

    def is_done(self, round_no: int) -> bool:
        return round_no >= len(self.tasks)

    def result(self) -> MatchResult:
        ranking = sorted(self.scores, key=lambda k: self.scores[k], reverse=True)
        return MatchResult(scores=dict(self.scores), ranking=ranking, details={"per_agent": self.detail})
