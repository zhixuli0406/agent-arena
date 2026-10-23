"""Two-axis ELO: a model axis (compares models) and a prompt axis (compares operators), independent of each other.

Updates use a pre-match snapshot: every pair's expected score is computed from pre-match ratings and the deltas
are summed and applied once, so the result is order-invariant; with N≥3 the participant order can't change the outcome.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .types import MatchResult, Participant

K = 32.0
BASE = 1500.0


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Ratings:
    def __init__(self, path: str = ""):
        self.path = path
        self.data: dict[str, dict[str, float]] = {"model": {}, "prompt": {}, "team": {}}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)  # fail fast: a corrupt file blows up before the match, not after a wasted match
            for axis in self.data:
                self.data[axis] = loaded.get(axis, {})

    def get(self, axis: str, key: str) -> float:
        return self.data[axis].get(key, BASE)

    def set(self, axis: str, key: str, value: float) -> None:
        self.data[axis][key] = value

    def save(self) -> None:
        if not self.path:
            return
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # each write uses its own temp file, so processes saving at once can't truncate the same .tmp
        fd, tmp = tempfile.mkstemp(dir=parent or ".", prefix=os.path.basename(self.path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # atomic replace: an interrupted write can't leave a half-written, corrupt file
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


@contextmanager
def locked(path: str) -> Iterator[None]:
    """Cross-process lock on the ratings file (held for the whole read -> modify -> write). Each CLI match is its own
    process, which event-loop atomicity doesn't cover. Platforms without fcntl (Windows) fall back to no lock."""
    if not path:
        yield
        return
    try:
        import fcntl
    except ImportError:
        yield
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path + ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _axis_key(participant: "Participant", axis: str) -> str:
    if axis == "model":
        return participant.spec.model or participant.spec.adapter
    return participant.spec.prompt_author


def update_from_result(
    ratings: Ratings, participants: list["Participant"], result: "MatchResult",
    teams: dict[str, str] | None = None, team_scores: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    """Update both axes from the match result and return each participant's ELO change.

    Free-for-all: every pair compares individual scores.
    Teams (teams = {participant id: team name}): win/loss is decided by team totals, and each player is compared once
    against the opposing team's average rating. Teammates are not compared with each other (otherwise they would take
    points off one another, and the player carrying the team would drag teammates down).
    """
    if teams and team_scores:
        return _update_team_match(ratings, participants, teams, team_scores)
    snapshot: dict[tuple[str, str], float] = {}

    def snap(axis: str, key: str) -> float:
        if (axis, key) not in snapshot:
            snapshot[(axis, key)] = ratings.get(axis, key)
        return snapshot[(axis, key)]

    deltas = {p.id: {"model": 0.0, "prompt": 0.0} for p in participants}
    agg: dict[tuple[str, str], float] = {}

    for i in range(len(participants)):
        for j in range(i + 1, len(participants)):
            a, b = participants[i], participants[j]
            sa, sb = result.scores.get(a.id, 0.0), result.scores.get(b.id, 0.0)
            outcome_a = 1.0 if sa > sb else 0.0 if sa < sb else 0.5
            for axis in ("model", "prompt"):
                ka, kb = _axis_key(a, axis), _axis_key(b, axis)
                if ka == kb:
                    continue  # same key (e.g. both use the same model): skip on this axis to avoid self-cancelling distortion
                ra, rb = snap(axis, ka), snap(axis, kb)
                da = K * (outcome_a - expected(ra, rb))
                db = K * ((1.0 - outcome_a) - expected(rb, ra))
                agg[(axis, ka)] = agg.get((axis, ka), 0.0) + da
                agg[(axis, kb)] = agg.get((axis, kb), 0.0) + db
                deltas[a.id][axis] += da
                deltas[b.id][axis] += db

    for (axis, key), d in agg.items():
        ratings.set(axis, key, snapshot[(axis, key)] + d)
    return deltas


def _update_team_match(
    ratings: Ratings, participants: list["Participant"], teams: dict[str, str], team_scores: dict[str, float],
) -> dict[str, dict[str, float]]:
    deltas = {p.id: {"model": 0.0, "prompt": 0.0} for p in participants}
    snapshot = {(axis, _axis_key(p, axis)): ratings.get(axis, _axis_key(p, axis))
                for p in participants for axis in ("model", "prompt")}
    agg: dict[tuple[str, str], float] = {}
    seats: dict[tuple[str, str], int] = {}
    for p in participants:
        mine = team_scores.get(teams[p.id], 0.0)
        others = sorted({teams[q.id] for q in participants} - {teams[p.id]})
        for axis in ("model", "prompt"):
            key = _axis_key(p, axis)
            parts = []
            for other in others:              # more than two teams: compare against each team once, then average
                opp = [snapshot[(axis, _axis_key(q, axis))] for q in participants
                       if teams[q.id] == other and _axis_key(q, axis) != key]
                if not opp:
                    continue  # that team is all the same key (e.g. same model): nothing to compare on this axis
                theirs = team_scores.get(other, 0.0)
                outcome = 1.0 if mine > theirs else 0.0 if mine < theirs else 0.5
                parts.append(outcome - expected(snapshot[(axis, key)], sum(opp) / len(opp)))
            if not parts:
                continue
            d = K * sum(parts) / len(parts)
            agg[(axis, key)] = agg.get((axis, key), 0.0) + d
            seats[(axis, key)] = seats.get((axis, key), 0) + 1
            deltas[p.id][axis] += d
    for (axis, key), d in agg.items():
        # how many seats one key held in this match (e.g. two teammates reporting the same model): count it as one game, take the average
        ratings.set(axis, key, snapshot[(axis, key)] + d / seats[(axis, key)])
    return deltas


def update_team_elo(ratings: Ratings, team_scores: dict[str, float]) -> dict[str, float]:
    """Team-axis ELO: pairwise updates from team totals; the pre-match snapshot keeps it order-invariant."""
    teams = list(team_scores)
    snapshot = {t: ratings.get("team", t) for t in teams}
    agg = {t: 0.0 for t in teams}
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            ta, tb = teams[i], teams[j]
            sa, sb = team_scores[ta], team_scores[tb]
            outcome_a = 1.0 if sa > sb else 0.0 if sa < sb else 0.5
            ra, rb = snapshot[ta], snapshot[tb]
            agg[ta] += K * (outcome_a - expected(ra, rb))
            agg[tb] += K * ((1.0 - outcome_a) - expected(rb, ra))
    for t in teams:
        ratings.set("team", t, snapshot[t] + agg[t])
    return dict(agg)
