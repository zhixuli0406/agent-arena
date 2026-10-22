"""斷路器測試：逾時與輪數上限都要以 DEGRADED 結束並顯式記錄原因。"""

from __future__ import annotations

from arena.engine import run_match
from arena.types import AgentSpec, MatchConfig

_Q = [{"id": "q1", "prompt": "x", "answer": "1", "kind": "contains"}]


async def test_timeout_degrades(tmp_path):
    cfg = MatchConfig(
        mode="quiz",
        mode_config={"questions": _Q},
        ratings_path="",
        timeout_seconds=0.3,
        agents=[
            AgentSpec(id="slow", adapter="mock", model="m1", prompt_author="a",
                      params={"answers": ["1"], "delay": 2.0}),
            AgentSpec(id="fast", adapter="mock", model="m2", prompt_author="b",
                      params={"answers": ["1"]}),
        ],
    )
    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert report.status == "DEGRADED"
    assert any("slow" in r and "timeout" in r for r in report.degraded_reasons)
    # 逾時者該題算錯、守時者該題算對
    assert report.result.scores["fast"] == 1.0
    assert report.result.scores["slow"] == 0.0


async def test_max_rounds_cap(tmp_path):
    # 題目比 max_rounds 多，應在上限處 DEGRADED 中止
    many = [{"id": f"q{i}", "prompt": "x", "answer": "1", "kind": "contains"} for i in range(10)]
    cfg = MatchConfig(
        mode="quiz",
        mode_config={"questions": many},
        ratings_path="",
        max_rounds=3,
        agents=[
            AgentSpec(id="a", adapter="mock", prompt_author="a", params={"reply": "1"}),
            AgentSpec(id="b", adapter="mock", prompt_author="b", params={"reply": "1"}),
        ],
    )
    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert report.status == "DEGRADED"
    assert any("max_rounds" in r for r in report.degraded_reasons)
