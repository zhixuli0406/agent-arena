"""CLI entry point: read the config, run one match, print the match report."""

from __future__ import annotations

import argparse
import asyncio

import yaml

from .engine import MatchReport, run_match
from .types import AgentSpec, MatchConfig

_STATUS_MARK = {"COMPLETE": "✅", "DEGRADED": "⚠️", "PARTIAL": "◐"}


def _author_of(cfg: MatchConfig, agent_id: str) -> str:
    for s in cfg.agents:
        if s.id == agent_id:
            return s.prompt_author
    return "?"


def _model_of(cfg: MatchConfig, agent_id: str) -> str:
    for s in cfg.agents:
        if s.id == agent_id:
            return s.model or s.adapter
    return "?"


def print_report(report: MatchReport, cfg: MatchConfig) -> None:
    mark = _STATUS_MARK.get(report.status, "?")
    print()
    print(f"=== Match report {report.match_id} · {report.mode} · {mark} {report.status} ===")
    print()
    print(f"{'Rank':<5}{'Agent':<12}{'Model':<18}{'Operator':<14}{'Score':>6}  ELOΔ(model/prompt)")
    print("-" * 78)
    result = report.result
    if result:
        for rank, agent_id in enumerate(result.ranking, 1):
            d = report.elo_deltas.get(agent_id, {"model": 0.0, "prompt": 0.0})
            print(
                f"{rank:<5}{agent_id:<12}{_model_of(cfg, agent_id):<18}{_author_of(cfg, agent_id):<14}"
                f"{result.scores.get(agent_id, 0.0):>6.1f}  {d['model']:+.1f} / {d['prompt']:+.1f}"
            )
    print()
    print("Usage:")
    for agent_id, u in report.usage_totals.items():
        print(
            f"  {agent_id:<12} in={u['input_tokens']} out={u['output_tokens']} "
            f"wall={u['wall_seconds']:.1f}s"
        )
    if report.degraded_reasons:
        print()
        print("⚠️ Degraded/abnormal (recorded explicitly, not silently swallowed):")
        for r in report.degraded_reasons:
            print(f"  - {r}")
    print()
    print(f"transcript: {report.transcript_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent Arena — run one match")
    ap.add_argument("--config", required=True, help="match config YAML")
    ap.add_argument("--runs-dir", default="runs", help="transcript output directory")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = MatchConfig.from_dict(yaml.safe_load(f))

    report = asyncio.run(run_match(cfg, runs_dir=args.runs_dir))
    print_report(report, cfg)


if __name__ == "__main__":
    main()
