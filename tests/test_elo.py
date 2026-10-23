"""ELO tests: a single match is zero-sum/symmetric and order-invariant with respect to participant order."""

from __future__ import annotations

from arena.elo import Ratings, expected, update_from_result
from arena.types import AgentSpec, MatchResult, Participant


def _p(pid: str, model: str, author: str) -> Participant:
    return Participant(spec=AgentSpec(id=pid, adapter="mock", model=model, prompt_author=author))


def test_expected_symmetry():
    assert abs(expected(1500, 1500) - 0.5) < 1e-12
    assert abs(expected(1600, 1400) + expected(1400, 1600) - 1.0) < 1e-12


def test_order_invariant_three_players():
    players = [_p("A", "mA", "aA"), _p("B", "mB", "aB"), _p("C", "mC", "aC")]
    res = MatchResult(scores={"A": 3.0, "B": 2.0, "C": 1.0}, ranking=["A", "B", "C"])

    r1 = Ratings("")
    update_from_result(r1, players, res)
    r2 = Ratings("")
    update_from_result(r2, list(reversed(players)), res)

    for axis in ("model", "prompt"):
        assert set(r1.data[axis]) == set(r2.data[axis])
        for key in r1.data[axis]:
            assert abs(r1.data[axis][key] - r2.data[axis][key]) < 1e-9


def test_zero_sum_single_match():
    players = [_p("A", "mA", "aA"), _p("B", "mB", "aB")]
    res = MatchResult(scores={"A": 1.0, "B": 0.0}, ranking=["A", "B"])
    r = Ratings("")
    deltas = update_from_result(r, players, res)
    assert abs(deltas["A"]["model"] + deltas["B"]["model"]) < 1e-9


def test_parallel_processes_do_not_lose_rating_updates(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "ladder.json"
    code = (
        "import sys\n"
        "from arena.elo import Ratings, locked\n"
        "for _ in range(40):\n"
        "    with locked(sys.argv[1]):\n"
        "        r = Ratings(sys.argv[1]); r.set('model', 'm', r.get('model', 'm') + 1); r.save()\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(path)]) for _ in range(4)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    from arena.elo import BASE, Ratings
    assert Ratings(str(path)).get("model", "m") == BASE + 160     # 4 processes × 40 writes, none lost
