"""Team matches: aggregated team scoring and ranking (many-vs-many / teams)."""

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
    assert 4.0 < det["team_scores"]["Red"] <= 6.0   # two players each get 2 right: 1 point per question + speed bonus (at most 0.5)
    assert det["team_scores"]["Blue"] == 0.0
    assert det["team_ranking"][0] == "Red"
    assert set(det["teams"]["Red"]) == {"a1", "a2"}
    assert len(det["teams"]["Blue"]) == 2


async def test_team_elo_teammates_move_together(tmp_path):
    # team match: everyone on the winning team gains, everyone on the losing team loses; teammates aren't compared with each other
    rep = await run_match(_cfg(tmp_path), runs_dir=str(tmp_path / "runs"))
    d = rep.elo_deltas
    assert d["a1"]["prompt"] > 0 and d["a2"]["prompt"] > 0
    assert d["b1"]["prompt"] < 0 and d["b2"]["prompt"] < 0
    # same starting rating, same opponents -> teammates change by the same amount (the free-for-all formula would give more to the teammate who answered more/faster and take from the other)
    assert abs(d["a1"]["prompt"] - d["a2"]["prompt"]) < 1e-9
    assert abs(d["a1"]["prompt"] - 16.0) < 1e-9          # 1500 vs 1500, K=32 × (1 − 0.5)


async def test_team_ladder_can_be_disabled(tmp_path):
    import json
    cfg = _cfg(tmp_path)
    cfg.team_ladder = False
    await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert json.loads((tmp_path / "r.json").read_text())["team"] == {}


async def test_team_same_model_key_counts_once(tmp_path):
    import json
    cfg = _cfg(tmp_path)
    for a in cfg.agents:
        a.model = "red-model" if a.id.startswith("a") else "blue-model"
    await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    model = json.loads((tmp_path / "r.json").read_text())["model"]
    assert model == {"red-model": 1516.0, "blue-model": 1484.0}    # not ±32


def test_three_team_elo_compares_against_each_team():
    from arena.elo import Ratings, update_from_result
    from arena.types import MatchResult, Participant
    specs = [AgentSpec(id=i, adapter="mock", model=i, prompt_author=i, team=t) for i, t in
             (("a", "A"), ("b", "B"), ("c", "C"))]
    ps = [Participant(spec=s, adapter=None) for s in specs]
    teams = {"a": "A", "b": "B", "c": "C"}
    d = update_from_result(Ratings(""), ps, MatchResult(scores={}, ranking=[]), teams, {"A": 3.0, "B": 2.0, "C": 1.0})
    # second place beats C and loses to A: net change is 0 from equal ratings (the old version only compared with the top score and counted it as a total loss)
    assert abs(d["b"]["prompt"]) < 1e-9 and d["a"]["prompt"] > 0 > d["c"]["prompt"]
