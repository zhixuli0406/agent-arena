"""規則引擎：跑回合、蒐集動作、交給 mode 結算、留痕、斷路器、更新 ELO。

引擎不懂任何一種玩法，也不懂任何一家模型；它只懂「回合」與「留痕」。
"""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field

from .adapters import build_adapter
from .adapters.base import AdapterUnavailable
from .elo import Ratings, update_from_result, update_team_elo
from .modes import build_mode
from .security import redact_spec
from .transcript import Transcript
from .types import Action, Event, MatchConfig, MatchResult, Observation, Participant


@dataclass
class MatchReport:
    match_id: str
    mode: str
    status: str  # COMPLETE / DEGRADED / PARTIAL
    result: MatchResult | None
    elo_deltas: dict[str, dict[str, float]]
    transcript_path: str
    degraded_reasons: list[str] = field(default_factory=list)
    usage_totals: dict[str, dict[str, float]] = field(default_factory=dict)


async def _act(participant: Participant, obs: Observation, timeout: float) -> Action:
    """把 adapter 動作包在超時與例外防護裡。失敗一律回成帶 error 的 Action，不讓整局崩潰。"""
    try:
        action = await asyncio.wait_for(participant.adapter.act(obs), timeout=timeout)
    except asyncio.TimeoutError:
        action = Action(content="", meta={"error": f"timeout>{timeout}s"})
    except AdapterUnavailable as e:
        action = Action(content="", meta={"error": f"unavailable: {e}"})
    except Exception as e:  # noqa: BLE001 — 對戰不因單一代理出錯而中斷，但要顯式記錄
        action = Action(content="", meta={"error": f"{type(e).__name__}: {e}"})
    action.meta["t_finish"] = time.monotonic()  # 供未來首殺類 mode 判完成先後
    return action


async def run_match(cfg: MatchConfig, runs_dir: str = "runs", match_id: str | None = None) -> MatchReport:
    match_id = match_id or (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    os.makedirs(runs_dir, exist_ok=True)
    transcript_path = os.path.join(runs_dir, match_id + ".jsonl")

    participants = [Participant(spec=s, adapter=build_adapter(s)) for s in cfg.agents]
    ratings = Ratings(cfg.ratings_path)  # fail-fast：壞檔在賽前就炸
    rng = random.Random(cfg.seed)
    mode = build_mode(cfg.mode, cfg.mode_config)

    status = "COMPLETE"
    degraded: list[str] = []
    usage_totals: dict[str, dict[str, float]] = {
        p.id: {"input_tokens": 0.0, "output_tokens": 0.0, "wall_seconds": 0.0} for p in participants
    }
    deltas: dict[str, dict[str, float]] = {p.id: {"model": 0.0, "prompt": 0.0} for p in participants}
    result: MatchResult | None = None
    round_no = 0
    t0 = time.monotonic()

    with Transcript(transcript_path) as tr:
        tr.write(
            Event(
                type="match_start",
                round=0,
                data={
                    "match_id": match_id,
                    "mode": cfg.mode,
                    "agents": [redact_spec(asdict(p.spec)) for p in participants],
                },
                ts=time.time(),
            )
        )

        started = False
        try:
            mode.setup(participants, rng)
            await mode.on_start(match_id)
            started = True
        except PermissionError as e:
            status = "PARTIAL"
            degraded.append(f"SECURITY: {e}")
            tr.write(Event(type="startup_error", round=0, data={"error": str(e), "kind": "security"}, ts=time.time()))
        except Exception as e:  # noqa: BLE001
            status = "PARTIAL"
            degraded.append(f"啟動失敗: {type(e).__name__}: {e}")
            tr.write(Event(type="startup_error", round=0, data={"error": f"{type(e).__name__}: {e}"}, ts=time.time()))

        try:
            while started:
                round_no += 1
                if round_no > cfg.max_rounds:
                    status = "DEGRADED"
                    degraded.append(f"超過 max_rounds={cfg.max_rounds}")
                    break
                remaining = cfg.max_wall_seconds - (time.monotonic() - t0)
                if remaining <= 0:
                    status = "DEGRADED"
                    degraded.append(f"超過 max_wall_seconds={cfg.max_wall_seconds}")
                    break

                obs_map = {p.id: mode.observe(round_no, p) for p in participants}
                active = [p for p in participants if obs_map[p.id] is not None]
                if not active:
                    break  # mode 已出完題，正常結束

                for p in active:
                    tr.write(
                        Event(type="observation", round=round_no, agent=p.id, data={"task": obs_map[p.id].task}, ts=time.time())
                    )

                step_timeout = min(cfg.timeout_seconds, remaining)
                try:
                    actions = await asyncio.wait_for(
                        asyncio.gather(*[_act(p, obs_map[p.id], step_timeout) for p in active]),
                        timeout=remaining + 1.0,
                    )
                except asyncio.TimeoutError:
                    status = "DEGRADED"
                    degraded.append("整輪超過剩餘牆鐘預算")
                    break

                for p, a in zip(active, actions):
                    u = a.usage
                    usage_totals[p.id]["input_tokens"] += u.input_tokens
                    usage_totals[p.id]["output_tokens"] += u.output_tokens
                    usage_totals[p.id]["wall_seconds"] += u.wall_seconds
                    tr.write(
                        Event(
                            type="action",
                            round=round_no,
                            agent=p.id,
                            data={"content": (a.content or "")[:1000], "error": a.error, "usage": asdict(u)},
                            ts=time.time(),
                        )
                    )
                    if a.error:
                        degraded.append(f"{p.id} r{round_no}: {a.error}")
                    for ev in await mode.apply(round_no, p, a):
                        tr.write(ev)

                if mode.is_done(round_no):
                    break
        finally:
            try:
                await mode.on_end()
            except Exception as e:  # noqa: BLE001
                degraded.append(f"on_end 失敗: {type(e).__name__}: {e}")

        result = mode.result()
        if degraded and status == "COMPLETE":
            status = "DEGRADED"

        # 組隊聚合：任一參賽者設了 team 才啟用；未設者自成一隊。支援多對多與組隊對戰。
        teams_present = any(p.spec.team for p in participants)
        team_scores: dict[str, float] = {}
        if teams_present:
            members: dict[str, list[str]] = {}
            for p in participants:
                members.setdefault(p.spec.team or p.id, []).append(p.id)
            team_scores = {t: sum(result.scores.get(a, 0.0) for a in ms) for t, ms in members.items()}
            result.details["teams"] = members
            result.details["team_scores"] = team_scores
            result.details["team_ranking"] = sorted(team_scores, key=lambda t: team_scores[t], reverse=True)

        tr.write(
            Event(
                type="result",
                round=round_no,
                data={"scores": result.scores, "ranking": result.ranking, "status": status},
                ts=time.time(),
            )
        )
        if teams_present:
            tr.write(
                Event(
                    type="teams",
                    round=round_no,
                    data={"members": result.details["teams"], "team_scores": team_scores,
                          "team_ranking": result.details["team_ranking"]},
                    ts=time.time(),
                )
            )

        # 只有乾淨完成（COMPLETE）才更新永久 ELO，避免逾時/不可用等基建失敗汙染技能評分
        if status == "COMPLETE":
            deltas = update_from_result(ratings, participants, result)
            if teams_present:
                team_deltas = update_team_elo(ratings, team_scores)
                tr.write(Event(type="team_elo", round=round_no, data=team_deltas, ts=time.time()))
            ratings.save()
            tr.write(Event(type="elo", round=round_no, data=deltas, ts=time.time()))
        else:
            degraded.append(f"ELO 未更新（狀態 {status}）")
            tr.write(Event(type="elo_skipped", round=round_no, data={"status": status}, ts=time.time()))

    return MatchReport(
        match_id=match_id,
        mode=cfg.mode,
        status=status,
        result=result,
        elo_deltas=deltas,
        transcript_path=transcript_path,
        degraded_reasons=degraded,
        usage_totals=usage_totals,
    )
