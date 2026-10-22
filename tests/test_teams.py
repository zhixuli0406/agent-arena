"""組隊對戰：團隊聚合計分與排名（多對多/組隊）。"""

from __future__ import annotations

from arena.engine import run_match
from arena.types import AgentSpec, MatchConfig

_Q = [
    {"id": "q1", "prompt": "日本首都？", "answer": "東京", "kind": "contains"},
    {"id": "q2", "prompt": "17*23=?", "answer": "391", "kind": "numeric"},
]


def _cfg(tmp_path) -> MatchConfig:
    mk = lambda i, ans: AgentSpec(id=i, adapter="mock", model=i, prompt_author=i, team=("Red" if i[0] == "a" else "Blue"),
                                  params={"answers": ans})
    return MatchConfig(
        mode="quiz",
        mode_config={"questions": _Q},
        ratings_path=str(tmp_path / "r.json"),
        agents=[mk("a1", ["東京", "391"]), mk("a2", ["東京", "391"]),
                mk("b1", ["大阪", "390"]), mk("b2", ["大阪", "390"])],
    )


async def test_team_aggregate_and_rank(tmp_path):
    rep = await run_match(_cfg(tmp_path), runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE"
    det = rep.result.details
    assert det["team_scores"]["Red"] == 4.0   # 兩名各答對 2 題
    assert det["team_scores"]["Blue"] == 0.0
    assert det["team_ranking"][0] == "Red"
    assert set(det["teams"]["Red"]) == {"a1", "a2"}
    assert len(det["teams"]["Blue"]) == 2
