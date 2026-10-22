"""CLI 進入點：讀設定、跑一局、印戰報。"""

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
    print(f"=== 戰報 {report.match_id} · {report.mode} · {mark} {report.status} ===")
    print()
    print(f"{'名次':<4}{'代理':<12}{'模型':<18}{'操盤手':<14}{'得分':>6}  ELOΔ(模型/提示詞)")
    print("-" * 78)
    result = report.result
    if result:
        for rank, agent_id in enumerate(result.ranking, 1):
            d = report.elo_deltas.get(agent_id, {"model": 0.0, "prompt": 0.0})
            print(
                f"{rank:<4}{agent_id:<12}{_model_of(cfg, agent_id):<18}{_author_of(cfg, agent_id):<14}"
                f"{result.scores.get(agent_id, 0.0):>6.1f}  {d['model']:+.1f} / {d['prompt']:+.1f}"
            )
    print()
    print("用量：")
    for agent_id, u in report.usage_totals.items():
        print(
            f"  {agent_id:<12} in={u['input_tokens']} out={u['output_tokens']} "
            f"wall={u['wall_seconds']:.1f}s"
        )
    if report.degraded_reasons:
        print()
        print("⚠️ 降級/異常（已顯式記錄，未靜默吞掉）：")
        for r in report.degraded_reasons:
            print(f"  - {r}")
    print()
    print(f"transcript: {report.transcript_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent Arena — 跑一局對戰")
    ap.add_argument("--config", required=True, help="對戰設定 YAML")
    ap.add_argument("--runs-dir", default="runs", help="transcript 輸出目錄")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = MatchConfig.from_dict(yaml.safe_load(f))

    report = asyncio.run(run_match(cfg, runs_dir=args.runs_dir))
    print_report(report, cfg)


if __name__ == "__main__":
    main()
