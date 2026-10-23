"""CTF mode integration tests. Need docker and the arena-warmup image; skipped otherwise.

The C1 gate (rejecting host-side agentic agents) fires during setup and doesn't need docker, but the whole file shares one skip condition for simplicity.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from arena.engine import run_match
from arena.types import AgentSpec, MatchConfig


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _image_exists(name: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not (_docker_up() and _image_exists("arena-warmup")),
    reason="needs docker and the arena-warmup image (run docker build -t arena-warmup targets/warmup first)",
)


async def test_ctf_recon_solves(tmp_path):
    cfg = MatchConfig(
        mode="ctf",
        ratings_path="",
        max_rounds=8,
        timeout_seconds=30,
        mode_config={
            "provider": "local",
            "target": "arena-warmup",
            "flag": "FLAG{warmup_recon_ok}",
            "first_blood": True,
            "max_requests_per_agent": 6,
        },
        agents=[
            AgentSpec(id="recon", adapter="mock", model="m-solver", prompt_author="x",
                      params={"answers": ["GET /robots.txt", "GET /s3cr3t-admin", "SUBMIT FLAG{warmup_recon_ok}"]}),
            AgentSpec(id="flailer", adapter="mock", model="m-flail", prompt_author="y",
                      params={"reply": "GET /"}),
        ],
    )
    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert report.result.ranking[0] == "recon"
    assert report.result.scores["recon"] > 0
    assert report.result.scores["flailer"] == 0


async def test_ctf_rejects_host_agentic(tmp_path):
    cfg = MatchConfig(
        mode="ctf",
        ratings_path="",
        mode_config={"provider": "local", "target": "arena-warmup"},
        agents=[
            AgentSpec(id="hostagent", adapter="claude_cli", model="", prompt_author="x"),
            AgentSpec(id="m", adapter="mock", prompt_author="y", params={"reply": "GET /"}),
        ],
    )
    report = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert report.status == "PARTIAL"
    assert any("C1" in r or "SECURITY" in r for r in report.degraded_reasons)
