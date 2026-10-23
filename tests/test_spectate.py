"""The public CTF stream must never expose live target evidence or a flag."""

from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path

from fastapi.testclient import TestClient

from arena.engine import MatchReport
from arena.types import MatchResult
from server import runtime as rt
from server.app import app
from server.spectate import public_ctf_event


FLAG = "FLAG{spectator_must_not_see_this}"
MATCH_ID = "20990101-000000-abcdef"


def test_ctf_projection_is_fail_closed():
    events = [
        {"type": "match_start", "round": 0, "data": {"mode": "ctf", "agents": [
            {"id": "alice", "model": "model", "system_prompt": FLAG,
             "params": {"answers": [FLAG]}}]}},
        {"type": "observation", "round": 1, "agent": "alice", "data": {"task": FLAG}},
        {"type": "action", "round": 1, "agent": "alice", "data": {"content": "SUBMIT " + FLAG}},
        {"type": "commentary", "round": 1, "agent": "alice", "data": {"text": "I found " + FLAG}},
        {"type": "request", "round": 1, "agent": "alice", "data": {
            "method": "GET", "path": "/?flag=" + FLAG, "status": 200, "resp": FLAG}},
        {"type": "invalid_action", "round": 1, "agent": "alice", "data": {"content": FLAG}},
        {"type": "agent_error", "round": 1, "agent": "alice", "data": {"error": FLAG}},
        {"type": "startup_error", "round": 1, "data": {"error": FLAG}},
        {"type": "solve", "round": 1, "agent": "alice", "data": {"first": True, "flag": FLAG}},
        {"type": "result", "round": 1, "data": {"scores": {"alice": 10},
            "ranking": ["alice"], "status": "COMPLETE", "flag": FLAG}},
        {"type": "future_event", "round": 1, "data": {"flag": FLAG}},
    ]
    projected = [public_ctf_event(json.dumps(event)) for event in events]
    output = "\n".join(value for value in projected if value)
    assert FLAG not in output
    assert projected[1] is None and projected[3] is None and projected[5] is None and projected[7] is None and projected[10] is None
    assert json.loads(projected[2])["data"] == {}
    assert json.loads(projected[4])["data"] == {"method": "GET", "status": 200}
    assert public_ctf_event("not json") is None


def test_ctf_spectator_endpoint_filters_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "RUNS_DIR", str(tmp_path))
    transcript = Path(tmp_path, MATCH_ID + ".jsonl")
    transcript.write_text("\n".join(json.dumps(event) for event in [
        {"type": "match_start", "round": 0, "data": {"agents": [{"id": "alice", "system_prompt": FLAG}]}},
        {"type": "observation", "round": 1, "agent": "alice", "data": {"task": FLAG}},
        {"type": "action", "round": 1, "agent": "alice", "data": {"content": "SUBMIT " + FLAG}},
        {"type": "commentary", "round": 1, "agent": "alice", "data": {"text": "Found " + FLAG}},
        {"type": "request", "round": 1, "agent": "alice", "data": {"resp": FLAG}},
        {"type": "result", "round": 1, "data": {"scores": {"alice": 1},
            "ranking": ["alice"], "status": "COMPLETE"}},
    ]) + "\n", encoding="utf-8")
    done = Future()
    done.set_result(None)
    monkeypatch.setitem(rt.matches, MATCH_ID, {"mode": "ctf", "task": done})
    with TestClient(app) as client:
        response = client.get(f"/api/matches/{MATCH_ID}/stream")
    assert response.status_code == 200
    assert FLAG not in response.text
    assert "event: end" in response.text
    assert '"type": "action"' in response.text
    assert '"type": "result"' in response.text


def test_other_modes_keep_their_spectator_events(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "RUNS_DIR", str(tmp_path))
    Path(tmp_path, MATCH_ID + ".jsonl").write_text(
        json.dumps({"type": "observation", "round": 1, "data": {"task": "Question"}}) + "\n",
        encoding="utf-8",
    )
    done = Future()
    done.set_result(None)
    monkeypatch.setitem(rt.matches, MATCH_ID, {"mode": "quiz", "task": done})
    with TestClient(app) as client:
        response = client.get(f"/api/matches/{MATCH_ID}/stream")
    assert response.status_code == 200
    assert "Question" in response.text


def test_ctf_public_status_and_match_list_hide_fault_text(monkeypatch):
    report = MatchReport(
        match_id=MATCH_ID, mode="ctf", status="PARTIAL",
        result=MatchResult(scores={"alice": 0}, ranking=["alice"]),
        elo_deltas={}, transcript_path="", degraded_reasons=["provision error: " + FLAG],
        forfeits=["alice: " + FLAG],
    )
    done = Future()
    done.set_result(report)
    monkeypatch.setitem(rt.matches, MATCH_ID, {
        "mode": "ctf", "task": done, "started": 1, "players": ["alice"],
    })
    with TestClient(app) as client:
        status = client.get(f"/api/matches/{MATCH_ID}")
        listing = client.get("/api/lobby/matches")
    assert status.status_code == 200 and listing.status_code == 200
    assert FLAG not in status.text + listing.text
    assert status.json()["degraded"] == ["Details withheld"]
    assert status.json()["forfeits"] == ["Details withheld"]
    match = next(m for m in listing.json()["matches"] if m["match_id"] == MATCH_ID)
    assert match["forfeits"] == ["Details withheld"]
