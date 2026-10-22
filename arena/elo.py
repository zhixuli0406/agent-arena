"""雙軸 ELO：模型軸（比模型）與提示詞軸（比操盤手），各自獨立。

更新採「賽前快照」：所有 pair 的期望值都用賽前評分計算，delta 累加後一次套用，
因此對參賽者排列順序不變（order-invariant），N≥3 也不會因順序得到不同結果。
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import MatchResult, Participant

K = 32.0
BASE = 1500.0


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Ratings:
    def __init__(self, path: str = ""):
        self.path = path
        self.data: dict[str, dict[str, float]] = {"model": {}, "prompt": {}, "team": {}}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)  # fail-fast：壞檔在賽前就炸，不會整場白跑
            for axis in self.data:
                self.data[axis] = loaded.get(axis, {})

    def get(self, axis: str, key: str) -> float:
        return self.data[axis].get(key, BASE)

    def set(self, axis: str, key: str, value: float) -> None:
        self.data[axis][key] = value

    def save(self) -> None:
        if not self.path:
            return
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)  # 原子置換，寫入中斷不會留半截損毀檔


def _axis_key(participant: "Participant", axis: str) -> str:
    if axis == "model":
        return participant.spec.model or participant.spec.adapter
    return participant.spec.prompt_author


def update_from_result(
    ratings: Ratings, participants: list["Participant"], result: "MatchResult"
) -> dict[str, dict[str, float]]:
    """依對局結果做兩軸 pairwise 更新，回傳每位參賽者的 ELO 變化量。"""
    snapshot: dict[tuple[str, str], float] = {}

    def snap(axis: str, key: str) -> float:
        if (axis, key) not in snapshot:
            snapshot[(axis, key)] = ratings.get(axis, key)
        return snapshot[(axis, key)]

    deltas = {p.id: {"model": 0.0, "prompt": 0.0} for p in participants}
    agg: dict[tuple[str, str], float] = {}

    for i in range(len(participants)):
        for j in range(i + 1, len(participants)):
            a, b = participants[i], participants[j]
            sa, sb = result.scores.get(a.id, 0.0), result.scores.get(b.id, 0.0)
            outcome_a = 1.0 if sa > sb else 0.0 if sa < sb else 0.5
            for axis in ("model", "prompt"):
                ka, kb = _axis_key(a, axis), _axis_key(b, axis)
                if ka == kb:
                    continue  # 同 key（如都用同模型）在該軸不比較，避免自我抵銷失真
                ra, rb = snap(axis, ka), snap(axis, kb)
                da = K * (outcome_a - expected(ra, rb))
                db = K * ((1.0 - outcome_a) - expected(rb, ra))
                agg[(axis, ka)] = agg.get((axis, ka), 0.0) + da
                agg[(axis, kb)] = agg.get((axis, kb), 0.0) + db
                deltas[a.id][axis] += da
                deltas[b.id][axis] += db

    for (axis, key), d in agg.items():
        ratings.set(axis, key, snapshot[(axis, key)] + d)
    return deltas


def update_team_elo(ratings: Ratings, team_scores: dict[str, float]) -> dict[str, float]:
    """團隊軸 ELO：以各隊總分 pairwise 更新，賽前快照確保 order-invariant。"""
    teams = list(team_scores)
    snapshot = {t: ratings.get("team", t) for t in teams}
    agg = {t: 0.0 for t in teams}
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            ta, tb = teams[i], teams[j]
            sa, sb = team_scores[ta], team_scores[tb]
            outcome_a = 1.0 if sa > sb else 0.0 if sa < sb else 0.5
            ra, rb = snapshot[ta], snapshot[tb]
            agg[ta] += K * (outcome_a - expected(ra, rb))
            agg[tb] += K * ((1.0 - outcome_a) - expected(rb, ra))
    for t in teams:
        ratings.set("team", t, snapshot[t] + agg[t])
    return dict(agg)
