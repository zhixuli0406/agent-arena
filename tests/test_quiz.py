"""End-to-end tests for quiz mode and the engine (all mock, offline, deterministic), including grade false-positive regressions."""

from __future__ import annotations

import json

from arena.engine import run_match
from arena.modes.quiz import grade
from arena.types import AgentSpec, MatchConfig

_QUESTIONS = [
    {"id": "q1", "prompt": "日本首都？", "answer": "東京", "kind": "contains"},
    {"id": "q2", "prompt": "17*23=?", "answer": "391", "kind": "numeric"},
    {"id": "q3", "prompt": "最矮者？", "answer": "C", "kind": "choice"},
]


def _cfg(tmp_path) -> MatchConfig:
    return MatchConfig(
        mode="quiz",
        mode_config={"questions": _QUESTIONS},
        ratings_path=str(tmp_path / "ratings.json"),
        agents=[
            AgentSpec(id="alpha", adapter="mock", model="mock-smart", prompt_author="x",
                      params={"answers": ["東京", "391", "C"]}),
            AgentSpec(id="beta", adapter="mock", model="mock-dumb", prompt_author="y",
                      params={"answers": ["大阪", "390", "A"]}),
        ],
    )


async def test_alpha_sweeps(tmp_path):
    report = await run_match(_cfg(tmp_path), runs_dir=str(tmp_path / "runs"))
    assert report.status == "COMPLETE"
    assert 3.0 < report.result.scores["alpha"] <= 4.5  # all 3 correct + speed bonus
    assert [d["correct"] for d in report.result.details["per_agent"]["alpha"]] == [True] * 3
    assert report.result.scores["beta"] == 0.0
    assert report.result.ranking[0] == "alpha"


async def test_elo_winner_gains(tmp_path):
    report = await run_match(_cfg(tmp_path), runs_dir=str(tmp_path / "runs"))
    assert report.elo_deltas["alpha"]["model"] > 0
    assert report.elo_deltas["alpha"]["prompt"] > 0
    assert report.elo_deltas["beta"]["model"] < 0


async def test_agent_public_summary_is_a_separate_redacted_event(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.mode_config["questions"] = _QUESTIONS[:1]
    cfg.agents[0].params["public_summaries"] = ["Compute directly with sk-abcdefghijklmnopqrstuvwxyz"]
    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    events = [json.loads(line) for line in open(report.transcript_path, encoding="utf-8")]
    notes = [event for event in events if event["type"] == "commentary"]
    assert notes == [{
        "type": "commentary", "round": 1, "agent": "alpha",
        "data": {"text": "Compute directly with ***"}, "ts": notes[0]["ts"],
    }]
    action = next(event for event in events if event["type"] == "action" and event["agent"] == "alpha")
    assert "public_summary" not in action["data"]


# --- grade regressions: false positives flagged in review must be blocked ---

def test_grade_exact_is_strict():
    assert grade({"answer": "東京", "kind": "exact"}, "東京")
    assert not grade({"answer": "東京", "kind": "exact"}, "首都是東京")  # strict: no substring match
    assert not grade({"answer": "C", "kind": "exact"}, "Carbon")


def test_grade_choice_no_false_positive():
    assert grade({"answer": "C", "kind": "choice"}, "The answer is C")
    assert grade({"answer": "C", "kind": "choice"}, "C")
    assert not grade({"answer": "C", "kind": "choice"}, "The answer is Carbon")
    assert not grade({"answer": "C", "kind": "choice"}, "I cannot decide")
    assert not grade({"answer": "A", "kind": "choice"}, "a quick brown fox")


def test_grade_contains_short_ascii_uses_boundary():
    # contains on short ASCII answers is upgraded to token-boundary matching
    assert not grade({"answer": "no", "kind": "contains"}, "Nope, the answer is yes")
    assert grade({"answer": "no", "kind": "contains"}, "the answer is no")


def test_grade_contains_cjk_substring():
    assert grade({"answer": "東京", "kind": "contains"}, "首都是東京。")
    assert not grade({"answer": "東京", "kind": "contains"}, "大阪")


def test_grade_numeric_takes_last_number():
    assert grade({"answer": "42", "kind": "numeric"}, "在 2024 年，答案是 42")  # takes the last number
    assert grade({"answer": "391", "kind": "numeric"}, "答案是 391")
    assert not grade({"answer": "390", "kind": "numeric"}, "答案是 391")


def test_choice_rejects_listing_every_option():
    from arena.modes.quiz import grade
    q = {"answer": "C", "kind": "choice"}
    assert grade(q, "C") and grade(q, "The answer is C")
    assert not grade(q, "A B C D") and not grade(q, "C or D")


def test_distractors_block_listing_all_weekdays():
    from arena.modes.quiz import grade
    q = {"answer": ["Monday", "星期一"], "kind": "contains", "distractors": ["Tuesday", "星期二", "Sunday"]}
    assert grade(q, "Monday") and grade(q, "星期一")
    assert not grade(q, "Monday Tuesday Sunday") and not grade(q, "星期一或星期二")


async def test_speed_bonus_rewards_fast_correct_but_accuracy_dominates(tmp_path):
    """Speed bonus: only for correct answers, more when faster; but one more correct answer always beats any speed difference."""
    from arena.modes.base import speed_bonus
    from arena.types import Action

    def act(elapsed, limit=120.0):
        return Action(content="x", meta={"elapsed": elapsed, "time_limit": limit})

    assert speed_bonus(act(0)) == 0.5
    assert speed_bonus(act(60)) == 0.25
    assert speed_bonus(act(120)) == 0.0 and speed_bonus(act(500)) == 0.0
    assert speed_bonus(Action(content="x")) == 0.0          # no bonus if elapsed time wasn't measured
    assert speed_bonus(act(0), cap=0) == 0.0                # speed_bonus: 0 disables it
    # single question: a correct answer (even at the last moment) always beats a wrong one
    assert 1 + speed_bonus(act(119.9)) > 0
    # whole match: speed can make up for one miss (the conversion is documented):
    # 4 correct at 5 s each ≈ 5.92 points, beats 5 correct averaging 80 s (≈ 5.83), loses to 5 correct averaging 60 s (6.25)
    fast_four = 4 * (1 + speed_bonus(act(5)))
    assert fast_four > 5 * (1 + speed_bonus(act(80)))
    assert fast_four < 5 * (1 + speed_bonus(act(60)))


def test_speed_bonus_config_validated():
    import pytest
    from arena.modes.quiz import QuizMode
    for bad in (1, 1.5, -0.1, True, "0.5"):
        with pytest.raises(ValueError):
            QuizMode({"questions": [{"prompt": "p", "answer": "a"}], "speed_bonus": bad})
    assert QuizMode({"questions": [{"prompt": "p", "answer": "a"}], "speed_bonus": 0}).speed_cap == 0.0
