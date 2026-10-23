"""Public CTF uses only the inert built-in target and needs no Docker or network."""

from __future__ import annotations

import json
import random

from arena.engine import run_match
from arena.modes.ctf import CTFMode
from arena.types import AgentSpec, MatchConfig, Participant
from server.spectate import public_ctf_event


def test_public_ctf_observation_has_all_supported_languages():
    mode = CTFMode({"provider": "builtin", "target": "arena-warmup"})
    participant = Participant(AgentSpec(id="recon", adapter="mock"))
    mode.setup([participant], random.Random(0))

    observation = mode.observe(1, participant)

    assert observation is not None
    localized = observation.state["i18n"]
    assert set(localized) == {"zh-TW", "zh-CN", "en", "ja"}
    assert "隔離" in localized["zh-TW"]["task"]
    assert "隔离" in localized["zh-CN"]["task"]
    assert "isolated" in localized["en"]["task"]
    assert "隔離" in localized["ja"]["task"]
    for value in localized.values():
        assert "GET /path" in value["task"] and "SUBMIT <flag>" in value["task"]
        assert value["instructions"]


async def test_builtin_ctf_runs_and_public_projection_hides_flag(tmp_path):
    flag = "FLAG{builtin_match_evidence}"
    cfg = MatchConfig(
        mode="ctf",
        ratings_path="",
        max_rounds=6,
        timeout_seconds=5,
        mode_config={
            "provider": "builtin",
            "target": "arena-warmup",
            "flag": flag,
            "first_blood": True,
            "max_requests_per_agent": 6,
            "ttl_seconds": 300,
        },
        agents=[
            AgentSpec(
                id="recon",
                adapter="mock",
                params={"answers": ["GET /robots.txt", "GET /s3cr3t-admin", f"SUBMIT {flag}"]},
            ),
            AgentSpec(id="other", adapter="mock", params={"reply": "GET /"}),
        ],
    )

    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))

    assert report.status == "COMPLETE"
    assert report.result is not None and report.result.ranking[0] == "recon"
    private = (tmp_path / "runs" / f"{report.match_id}.jsonl").read_text(encoding="utf-8")
    assert flag in private
    public = "\n".join(
        value
        for raw in private.splitlines()
        if (value := public_ctf_event(raw)) is not None
    )
    assert flag not in public
    assert any(json.loads(line)["type"] == "solve" for line in public.splitlines())

