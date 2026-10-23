"""Circuit breaker tests: hitting the round cap ends as DEGRADED with the reason recorded explicitly; a single agent timing out is only a forfeit (see test_engine_forfeit)."""

from __future__ import annotations

from arena.engine import run_match
from arena.types import AgentSpec, MatchConfig

_Q = [{"id": "q1", "prompt": "x", "answer": "1", "kind": "contains"}]


async def test_single_agent_timeout_is_forfeit_not_degraded(tmp_path):
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
    # a timeout is the agent's fault: record a forfeit and score the match as usual (a self-inflicted timeout can't void the match)
    assert report.status == "COMPLETE"
    assert report.rated is True
    assert any("slow" in r and "timeout" in r for r in report.forfeits)
    assert not report.degraded_reasons
    # the agent that timed out gets the question wrong, the punctual one gets it right
    assert 1.0 < report.result.scores["fast"] <= 1.5
    assert report.result.scores["slow"] == 0.0


async def test_max_rounds_cap(tmp_path):
    # more questions than max_rounds: should stop as DEGRADED at the cap
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
