"""Fault attribution: participant-caused timeouts/errors are only forfeits and the match is still rated; only infrastructure failures void it."""

from __future__ import annotations

import json
import os
import time

from arena import adapters as adapters_pkg
from arena.adapters.base import Adapter, AdapterUnavailable
from arena.engine import FORFEIT_STREAK_LIMIT, run_match
from arena.types import AgentSpec, MatchConfig

_Q = [{"id": f"q{i}", "prompt": "1+0=?", "answer": "1", "kind": "contains"} for i in range(5)]


def _cfg(tmp_path, agents, **kw) -> MatchConfig:
    return MatchConfig(
        mode="quiz",
        mode_config={"questions": kw.pop("questions", _Q)},
        ratings_path=str(tmp_path / "ratings.json"),
        timeout_seconds=kw.pop("timeout_seconds", 0.2),
        agents=agents,
        **kw,
    )


def _honest(aid="honest", model="m-honest"):
    return AgentSpec(id=aid, adapter="mock", model=model, prompt_author=aid, params={"reply": "1"})


def _staller(aid="staller", model="m-staller"):
    # stalls every question until timeout: simulates a loser disconnecting / not answering on purpose
    return AgentSpec(id=aid, adapter="mock", model=model, prompt_author=aid, params={"reply": "1", "delay": 30.0})


async def test_staller_every_round_still_rated_and_loses(tmp_path):
    cfg = _cfg(tmp_path, [_honest(), _staller()])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))

    assert rep.status == "COMPLETE"
    assert rep.rated is True
    assert rep.result.ranking[0] == "honest"
    assert rep.result.scores["staller"] == 0.0
    assert len(_Q) < rep.result.scores["honest"] <= len(_Q) * 1.5
    # ELO is updated: the loser (the side that timed out) loses points, the winner gains, and it's written to the ratings file
    assert rep.elo_deltas["staller"]["model"] < 0
    assert rep.elo_deltas["honest"]["model"] > 0
    saved = json.loads((tmp_path / "ratings.json").read_text(encoding="utf-8"))
    assert saved["model"]["m-staller"] < 1500 < saved["model"]["m-honest"]
    assert any(r.startswith("staller") and "timeout" in r for r in rep.forfeits)
    assert not rep.degraded_reasons

    # transcript: event types unchanged, but actions carry a forfeit field; elo present, no elo_skipped
    events = [json.loads(line) for line in open(rep.transcript_path, encoding="utf-8")]
    types = {e["type"] for e in events}
    assert "elo" in types and "elo_skipped" not in types
    staller_actions = [e for e in events if e["type"] == "action" and e["agent"] == "staller"]
    assert staller_actions and all(e["data"]["forfeit"] for e in staller_actions)


async def test_streak_withdraws_and_bounds_wall_clock(tmp_path):
    # withdrawn once consecutive forfeits hit the limit, then no longer waited on -> total time is about LIMIT timeouts, not one per question
    timeout = 0.3
    cfg = _cfg(tmp_path, [_honest(), _staller()], timeout_seconds=timeout)
    t0 = time.monotonic()
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    elapsed = time.monotonic() - t0

    assert rep.status == "COMPLETE"
    assert any("withdrawn" in r for r in rep.forfeits)
    assert elapsed < timeout * (FORFEIT_STREAK_LIMIT + 1) + 0.5
    events = [json.loads(line) for line in open(rep.transcript_path, encoding="utf-8")]
    withdrawn_flags = [e for e in events if e["type"] == "action" and e["data"].get("withdrawn")]
    assert len(withdrawn_flags) == 1


async def test_adapter_exception_is_forfeit(tmp_path, monkeypatch):
    class Boom(Adapter):
        async def act(self, obs):
            raise RuntimeError("player bug")

    monkeypatch.setitem(adapters_pkg.REGISTRY, "boom", Boom)
    cfg = _cfg(tmp_path, [_honest(), AgentSpec(id="buggy", adapter="boom", model="m-b", prompt_author="b")])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE" and rep.rated
    assert rep.result.ranking[0] == "honest"
    assert rep.elo_deltas["buggy"]["model"] < 0


async def test_all_agents_fail_same_round_is_void(tmp_path):
    # all agents failing at once = likely an infrastructure problem: nobody is blamed, no ELO
    cfg = _cfg(tmp_path, [_staller("s1", "m1"), _staller("s2", "m2")], questions=_Q[:1])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "DEGRADED"
    assert rep.rated is False
    assert any("all agents kept failing" in r for r in rep.degraded_reasons)
    assert not (tmp_path / "ratings.json").exists()


async def test_mid_match_all_fail_round_is_symmetric_not_void(tmp_path, monkeypatch):
    # both sides fail in round 2 (e.g. a brief outage), other rounds normal: symmetric, not voided, still rated
    class Flaky(Adapter):
        async def act(self, obs):
            if obs.round == 2:
                raise RuntimeError("blip")
            from arena.types import Action
            return Action(content=str(self.spec.params["reply"]))

    monkeypatch.setitem(adapters_pkg.REGISTRY, "flaky", Flaky)
    agents = [AgentSpec(id="good", adapter="flaky", model="m-g", prompt_author="g", params={"reply": "1"}),
              AgentSpec(id="bad", adapter="flaky", model="m-b", prompt_author="b", params={"reply": "0"})]
    rep = await run_match(_cfg(tmp_path, agents, questions=_Q[:3]), runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE" and rep.rated
    assert any("all agents failed at once" in r for r in rep.forfeits)
    assert rep.result.ranking[0] == "good"


async def test_adapter_unavailable_is_infra_and_void(tmp_path, monkeypatch):
    class Down(Adapter):
        async def act(self, obs):
            raise AdapterUnavailable("CLI not found")

    monkeypatch.setitem(adapters_pkg.REGISTRY, "down", Down)
    cfg = _cfg(tmp_path, [_honest(), AgentSpec(id="d", adapter="down", model="m-d", prompt_author="d")],
               questions=_Q[:1])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "DEGRADED"
    assert rep.rated is False
    assert rep.elo_deltas["honest"]["model"] == 0.0
    assert any("unavailable" in r for r in rep.degraded_reasons)


async def test_mode_crash_on_start_is_void(tmp_path):
    # mode startup failure (e.g. malformed questions) = not caused by a participant -> PARTIAL, no ELO
    cfg = _cfg(tmp_path, [_honest(), _staller()], questions=[{"id": "bad"}])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "PARTIAL"
    assert rep.rated is False


async def test_grading_exception_is_forfeit_not_crash(tmp_path, monkeypatch):
    # a participant's output makes the grader raise: that agent gets 0, the match is scored as usual
    from arena.modes.quiz import QuizMode

    orig = QuizMode.apply

    async def apply(self, round_no, participant, action):
        if action.content == "BOOM":
            raise ValueError("grader exploded")
        return await orig(self, round_no, participant, action)

    monkeypatch.setattr(QuizMode, "apply", apply)
    bomber = AgentSpec(id="bomber", adapter="mock", model="m-x", prompt_author="x", params={"reply": "BOOM"})
    rep = await run_match(_cfg(tmp_path, [_honest(), bomber], questions=_Q[:2]), runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE" and rep.rated
    assert rep.result.ranking[0] == "honest"
    assert any("bomber" in r and "grader exception" in r for r in rep.forfeits)


async def test_observe_crash_is_degraded_report_not_exception(tmp_path, monkeypatch):
    from arena.modes.quiz import QuizMode

    def observe(self, round_no, participant):
        raise KeyError("bank broken")

    monkeypatch.setattr(QuizMode, "observe", observe)
    rep = await run_match(_cfg(tmp_path, [_honest(), _staller()]), runs_dir=str(tmp_path / "runs"))
    assert rep.status == "DEGRADED" and rep.rated is False
    assert any("task generation failed" in r for r in rep.degraded_reasons)


async def test_transcript_redacts_secrets_in_content(tmp_path):
    leaky = AgentSpec(id="leaky", adapter="mock", model="m-l", prompt_author="l",
                      params={"reply": "my key is sk-proj-" + "z" * 30})
    rep = await run_match(_cfg(tmp_path, [_honest(), leaky], questions=_Q[:1]), runs_dir=str(tmp_path / "runs"))
    text = open(rep.transcript_path, encoding="utf-8").read()
    assert "sk-proj-zzzz" not in text


async def test_cli_nonzero_exit_is_agent_forfeit_not_void(tmp_path, monkeypatch):
    # host CLI ran but exited non-zero (model refused, agent crashed): participant forfeit, can't void the match
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text("#!/bin/sh\necho 'refused' >&2\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    cfg = _cfg(tmp_path, [_honest(), AgentSpec(id="c", adapter="claude_cli", model="", prompt_author="c")],
               questions=_Q[:1], timeout_seconds=10)
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE" and rep.rated
    assert any("AgentFailed" in r for r in rep.forfeits)
    assert rep.result.ranking[0] == "honest"


async def test_adapter_cannot_mark_its_own_failure_as_infra(tmp_path, monkeypatch):
    # Vettalon: an adapter returning Action(meta={"fault": "infra"}) must not void a match it is losing
    from arena.types import Action

    class Sneaky(Adapter):
        async def act(self, obs):
            return Action(content="", meta={"error": "pretend outage", "fault": "infra"})

    monkeypatch.setitem(adapters_pkg.REGISTRY, "sneaky", Sneaky)
    cfg = _cfg(tmp_path, [_honest(), AgentSpec(id="s", adapter="sneaky", model="m-s", prompt_author="s")], questions=_Q[:1])
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE" and rep.rated
