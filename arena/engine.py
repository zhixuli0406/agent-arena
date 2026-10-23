"""Rules engine: runs rounds, collects actions, hands them to the mode for scoring, writes the transcript, applies the circuit breaker, and updates ELO.

The engine knows nothing about any game mode or any model vendor; it only knows "rounds" and "the transcript".

Fault attribution (decides whether the match is rated):
- Attributable to a single participant (that agent timed out, its adapter raised, or it disconnected) -> that agent
  forfeits the round (0 points); the match is still scored and rated. Otherwise a losing player could disconnect or
  time out on purpose to void the match and dodge the rating loss.
- Infrastructure failure not caused by a participant (mode/provisioner crash, AdapterUnavailable = missing tool /
  unset key / endpoint down, all agents failing at once through the final round or nobody succeeding all match,
  circuit breaker tripped) -> status is not COMPLETE and ELO is not updated.
  An all-agents failure in a single mid-match round is symmetric (everyone gets 0), so it is only logged, not
  voided; this stops a loser from betting that the opponent also fails in order to void the match.
- A participant who forfeits FORFEIT_STREAK_LIMIT rounds in a row is withdrawn: its adapter is no longer called
  and it forfeits directly, so a dead agent can't drag every round out to the timeout (keeps the circuit
  breaker's anti-runaway intent).
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
from .elo import locked as ratings_lock
from .modes import build_mode
from .security import redact_spec, redact_text
from .transcript import Transcript
from .types import Action, Event, MatchConfig, MatchResult, Observation, Participant

# Consecutive forfeits before an agent is withdrawn (after that we stop waiting and record forfeits directly)
FORFEIT_STREAK_LIMIT = 3

# The two fault attributions in Action.meta["fault"]
FAULT_AGENT = "agent"   # Participant's fault: record a forfeit, match is still scored
FAULT_INFRA = "infra"   # Infrastructure failure: the whole match is unrated


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
    # Participant-caused failures (timeout/error/withdrawn): only affect that agent's score for that round; the match is not voided
    forfeits: list[str] = field(default_factory=list)
    rated: bool = False  # Whether this match updated the persistent ELO


async def _act(participant: Participant, obs: Observation, timeout: float) -> Action:
    """Wrap the adapter action in timeout and exception guards. Any failure comes back as an Action with an
    error, so one agent can't crash the match.

    meta["fault"] records attribution: timeouts and ordinary exceptions are the participant's fault (forfeit);
    AdapterUnavailable is an infrastructure failure such as a missing tool, unset key or unreachable endpoint,
    and is attributed to infra (the match is unrated).
    """
    t0 = time.monotonic()
    try:
        action = await asyncio.wait_for(participant.adapter.act(obs), timeout=timeout)
        # Attribution is the engine's call, never the adapter's: an adapter that returns normally can't mark
        # its own failure as "infra" (which would void a match it was losing).
        action.meta.pop("fault", None)
        if action.meta.get("error"):
            action.meta["fault"] = FAULT_AGENT
    except asyncio.TimeoutError:
        action = Action(content="", meta={"error": f"timeout>{timeout}s", "fault": FAULT_AGENT})
    except AdapterUnavailable as e:
        action = Action(content="", meta={"error": f"unavailable: {e}", "fault": FAULT_INFRA})
    except Exception as e:  # noqa: BLE001 — one agent's error must not stop the match, but it is recorded explicitly
        action = Action(content="", meta={"error": f"{type(e).__name__}: {e}", "fault": FAULT_AGENT})
    action.meta["t_finish"] = time.monotonic()  # lets future first-blood style modes tell who finished first
    # Answer time is measured on the server's own clock (task sent to answer received), so players can't fake it; modes use it for speed bonuses
    action.meta["elapsed"] = action.meta["t_finish"] - t0
    action.meta["time_limit"] = timeout
    return action


async def run_match(cfg: MatchConfig, runs_dir: str = "runs", match_id: str | None = None) -> MatchReport:
    match_id = match_id or (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    os.makedirs(runs_dir, exist_ok=True)
    transcript_path = os.path.join(runs_dir, match_id + ".jsonl")

    participants = [Participant(spec=s, adapter=build_adapter(s)) for s in cfg.agents]
    ratings = Ratings(cfg.ratings_path)  # fail fast: a corrupt file blows up before the match starts
    rng = random.Random(cfg.seed)
    mode = build_mode(cfg.mode, cfg.mode_config)

    status = "COMPLETE"
    degraded: list[str] = []       # infrastructure/circuit-breaker problems: make the match unrated
    forfeits: list[str] = []       # participant's own failures: recorded as forfeits only
    streak: dict[str, int] = {p.id: 0 for p in participants}
    withdrawn: set[str] = set()
    any_success = False          # whether at least one agent answered successfully during the match
    last_round_all_failed = False  # whether the last round actually played had every agent fail at once
    rounds_played = 0
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
            degraded.append(f"startup failed: {type(e).__name__}: {e}")
            tr.write(Event(type="startup_error", round=0, data={"error": f"{type(e).__name__}: {e}"}, ts=time.time()))

        try:
            while started:
                round_no += 1
                if round_no > cfg.max_rounds:
                    status = "DEGRADED"
                    degraded.append(f"exceeded max_rounds={cfg.max_rounds}")
                    break
                remaining = cfg.max_wall_seconds - (time.monotonic() - t0)
                if remaining <= 0:
                    status = "DEGRADED"
                    degraded.append(f"exceeded max_wall_seconds={cfg.max_wall_seconds}")
                    break

                try:
                    obs_map = {p.id: mode.observe(round_no, p) for p in participants}
                except Exception as e:  # noqa: BLE001 — task generation crashing is an infra problem: degrade honestly, no ELO
                    status = "DEGRADED"
                    degraded.append(f"r{round_no}: task generation failed {type(e).__name__}: {e}")
                    break
                active = [p for p in participants if obs_map[p.id] is not None]
                if not active:
                    break  # the mode has no more tasks; normal end
                callers = [p for p in active if p.id not in withdrawn]
                if not callers:
                    # everyone withdrawn = nobody is still playing; treat as an all-agents failure, no ELO
                    degraded.append(f"r{round_no}: all participants have withdrawn, ending early")
                    break

                for p in active:
                    tr.write(
                        Event(type="observation", round=round_no, agent=p.id, data={"task": obs_map[p.id].task}, ts=time.time())
                    )

                step_timeout = min(cfg.timeout_seconds, remaining)
                try:
                    called = await asyncio.wait_for(
                        asyncio.gather(*[_act(p, obs_map[p.id], step_timeout) for p in callers]),
                        timeout=remaining + 1.0,
                    )
                except asyncio.TimeoutError:
                    status = "DEGRADED"
                    degraded.append("round exceeded the remaining wall-clock budget")
                    break
                rounds_played += 1
                by_id = {p.id: a for p, a in zip(callers, called)}
                actions = [
                    by_id.get(p.id)
                    or Action(content="", meta={"error": "withdrawn", "fault": FAULT_AGENT})
                    for p in active
                ]

                # Every agent actually called this round failed (and there were at least two) -> likely an infra failure.
                # A single mid-match all-fail round is symmetric (everyone gets 0), so it is only logged;
                # only if it lasts through the final round (or nobody ever succeeded) is it an infra fault and the match unrated (see after the loop).
                round_all_failed = len(callers) >= 2 and all(by_id[p.id].error for p in callers)
                last_round_all_failed = round_all_failed
                if round_all_failed:
                    forfeits.append(f"r{round_no}: all agents failed at once (everyone scores 0)")
                if any(not by_id[p.id].error for p in callers):
                    any_success = True

                for p, a in zip(active, actions):
                    u = a.usage
                    usage_totals[p.id]["input_tokens"] += u.input_tokens
                    usage_totals[p.id]["output_tokens"] += u.output_tokens
                    usage_totals[p.id]["wall_seconds"] += u.wall_seconds
                    fault = a.meta.get("fault") if a.error else None
                    just_withdrawn = False
                    if a.error:
                        if fault == FAULT_INFRA:
                            degraded.append(f"{p.id} r{round_no}: {a.error}")
                        else:
                            forfeits.append(f"{p.id} r{round_no}: {a.error}")
                        streak[p.id] += 1
                        if streak[p.id] >= FORFEIT_STREAK_LIMIT and p.id not in withdrawn:
                            withdrawn.add(p.id)
                            just_withdrawn = True
                            forfeits.append(f"{p.id} r{round_no}: failed {streak[p.id]} rounds in a row, withdrawn")
                    else:
                        streak[p.id] = 0
                    public_summary = redact_text(str(a.meta.get("public_summary", "")).strip())
                    if public_summary:
                        tr.write(
                            Event(
                                type="commentary",
                                round=round_no,
                                agent=p.id,
                                data={"text": public_summary[:280]},
                                ts=time.time(),
                            )
                        )
                    # Event type is unchanged (the spectator frontend dispatches on it); fault info is attached to the action as extra fields
                    tr.write(
                        Event(
                            type="action",
                            round=round_no,
                            agent=p.id,
                            data={"content": redact_text((a.content or "")[:1000]),
                                  "error": redact_text(a.error) if a.error else a.error, "usage": asdict(u),
                                  "forfeit": bool(a.error) and fault != FAULT_INFRA, "fault": fault,
                                  "withdrawn": just_withdrawn},
                            ts=time.time(),
                        )
                    )
                    try:
                        events = await mode.apply(round_no, p, a)
                    except Exception as e:  # noqa: BLE001
                        # This agent's output crashed the grader: attribute it to the agent (0 this round) instead of crashing and voiding the match
                        forfeits.append(f"{p.id} r{round_no}: grader exception {type(e).__name__}")
                        events = []
                    for ev in events:
                        tr.write(ev)

                if mode.is_done(round_no):
                    break
        finally:
            try:
                await mode.on_end()
            except Exception as e:  # noqa: BLE001
                degraded.append(f"on_end failed: {type(e).__name__}: {e}")

        if rounds_played > 0 and (last_round_all_failed or not any_success):
            degraded.append("all agents kept failing through the final round (or nobody answered successfully all match); likely an infrastructure fault")

        result = mode.result()
        if degraded and status == "COMPLETE":
            status = "DEGRADED"

        # Team aggregation: enabled only if any participant sets team; those without one form their own team. Supports many-vs-many and team matches.
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
                data={"scores": result.scores, "ranking": result.ranking, "status": status,
                      "forfeits": len(forfeits)},
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

        # Only COMPLETE updates the persistent ELO. A participant's own timeouts/errors/disconnects are only forfeits
        # and don't degrade the status, so a loser can't void the match by failing on purpose; only infra failures degrade and go unrated.
        rated = status == "COMPLETE"
        if rated:
            # Re-read the latest ratings file before updating: with several matches running at once, this avoids
            # overwriting other matches' updates with a pre-match snapshot. Within one event loop there is no await
            # between read -> modify -> write; across processes (CLI running matches in parallel) a file lock serializes them.
            with ratings_lock(cfg.ratings_path):
                ratings = Ratings(cfg.ratings_path)
                team_of = {p.id: p.spec.team or p.id for p in participants} if teams_present else None
                deltas = update_from_result(ratings, participants, result, team_of, team_scores or None)
                if teams_present and cfg.team_ladder:
                    team_deltas = update_team_elo(ratings, team_scores)
                ratings.save()
            if teams_present and cfg.team_ladder:
                tr.write(Event(type="team_elo", round=round_no, data=team_deltas, ts=time.time()))
            tr.write(Event(type="elo", round=round_no, data=deltas, ts=time.time()))
        else:
            degraded.append(f"ELO not updated (status {status})")
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
        forfeits=forfeits,
        rated=rated,
    )
