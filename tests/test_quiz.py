"""quiz 模式與引擎的端到端測試（全用 mock，離線、確定性），含 grade 假陽性迴歸。"""

from __future__ import annotations

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
    assert report.result.scores["alpha"] == 3.0
    assert report.result.scores["beta"] == 0.0
    assert report.result.ranking[0] == "alpha"


async def test_elo_winner_gains(tmp_path):
    report = await run_match(_cfg(tmp_path), runs_dir=str(tmp_path / "runs"))
    assert report.elo_deltas["alpha"]["model"] > 0
    assert report.elo_deltas["alpha"]["prompt"] > 0
    assert report.elo_deltas["beta"]["model"] < 0


# --- grade 迴歸：評審點名的假陽性必須被擋掉 ---

def test_grade_exact_is_strict():
    assert grade({"answer": "東京", "kind": "exact"}, "東京")
    assert not grade({"answer": "東京", "kind": "exact"}, "首都是東京")  # 嚴格：不做子字串
    assert not grade({"answer": "C", "kind": "exact"}, "Carbon")


def test_grade_choice_no_false_positive():
    assert grade({"answer": "C", "kind": "choice"}, "The answer is C")
    assert grade({"answer": "C", "kind": "choice"}, "C")
    assert not grade({"answer": "C", "kind": "choice"}, "The answer is Carbon")
    assert not grade({"answer": "C", "kind": "choice"}, "I cannot decide")
    assert not grade({"answer": "A", "kind": "choice"}, "a quick brown fox")


def test_grade_contains_short_ascii_uses_boundary():
    # ASCII 短答案的 contains 自動升級為 token 邊界比對
    assert not grade({"answer": "no", "kind": "contains"}, "Nope, the answer is yes")
    assert grade({"answer": "no", "kind": "contains"}, "the answer is no")


def test_grade_contains_cjk_substring():
    assert grade({"answer": "東京", "kind": "contains"}, "首都是東京。")
    assert not grade({"answer": "東京", "kind": "contains"}, "大阪")


def test_grade_numeric_takes_last_number():
    assert grade({"answer": "42", "kind": "numeric"}, "在 2024 年，答案是 42")  # 取最後一個數字
    assert grade({"answer": "391", "kind": "numeric"}, "答案是 391")
    assert not grade({"answer": "390", "kind": "numeric"}, "答案是 391")
