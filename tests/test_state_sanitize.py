"""infra/sanitize_state.py: keep only expected fields before backing up to the public data branch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "infra" / "sanitize_state.py"
H = "a" * 64


def _run(tmp_path, kind, payload) -> tuple[int, object]:
    src, dst = tmp_path / "in.json", tmp_path / "out.json"
    src.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    rc = subprocess.run([sys.executable, "-I", str(SCRIPT), kind, str(src), str(dst)], capture_output=True).returncode
    return rc, (json.loads(dst.read_text()) if rc == 0 else None)


def test_lobby_state_keeps_only_valid_players(tmp_path):
    good = {"id": "p_0123456789", "name": "Ann", "rating": 1516.0, "games": 3, "agent": "x", "secret_hash": H}
    rc, out = _run(tmp_path, "lobby_state.json", {"version": 1, "evil": "GH_TOKEN=ghs_x", "players": [
        good,
        {**good, "id": "../../etc"},                 # bad id
        {**good, "secret_hash": "ghs_" + "x" * 60},  # not a sha256 hex
        {**good, "rating": float("1e308") * 10},     # inf → json "Infinity"
        {**good, "games": True},
        {**good, "extra": "smuggled"},
    ]})
    assert rc == 0
    kept = {**good, "extra_hashes": []}
    assert out == {"version": 1, "players": [kept, kept]}  # unknown field dropped, rest rejected


def test_lobby_state_keeps_valid_link_credentials(tmp_path):
    good = {"id": "p_0123456789", "name": "Ann", "rating": 1500.0, "games": 1, "agent": "", "secret_hash": H,
            "extra_hashes": ["b" * 64, "not-a-hash", "c" * 64]}
    rc, out = _run(tmp_path, "lobby_state.json", {"version": 1, "players": [good]})
    assert rc == 0 and out["players"][0]["extra_hashes"] == ["b" * 64, "c" * 64]


def test_ladder_rebuilt(tmp_path):
    rc, out = _run(tmp_path, "ladder.json", {"model": {"m": 1500, "bad": "x"}, "prompt": {"p_1": 1490.123},
                                             "smuggle": {"k": 1}})
    assert rc == 0
    assert out == {"model": {"m": 1500.0}, "prompt": {"p_1": 1490.12}, "team": {}}


def test_garbage_and_oversize_rejected(tmp_path):
    assert _run(tmp_path, "ladder.json", b"GH_TOKEN=ghs_abc\0PATH=/usr/bin")[0] == 1
    assert _run(tmp_path, "lobby_state.json", ["not", "a", "dict"])[0] == 1
    assert _run(tmp_path, "ladder.json", b"{" + b" " * 2_000_001 + b"}")[0] == 1
