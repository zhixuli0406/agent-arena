"""Team matchmaking: combine queue tickets (solo = 1 player, party = 2-3 players) into two teams of team_size each.

Rules (modeled on League of Legends party queue):
- Party members always end up on the same side; never split, never opponents.
- The two teams' average ratings should be as close as possible.
- Players on the same network (IP) may be teammates but never opponents: stops one person running alts to play themselves and farm rating.

Pure functions; no clock or state. Work is hard-capped (this runs on the server's event loop, and a stall freezes the whole site):
only combinations that exactly fill a team are enumerated, at most MAX_CANDIDATES candidate tickets, at most MAX_EVALS combinations per anchor,
and the search stops early once a balanced enough (within GOOD_GAP) result is found.
"""

from __future__ import annotations

from typing import Callable, Iterator, Sequence, TypeVar

T = TypeVar("T")
MAX_CANDIDATES = 8    # per anchor, only consider the tickets with the closest ratings
MAX_EVALS = 120       # max team-filling combinations evaluated per anchor
GOOD_GAP = 50.0       # accept immediately if the average rating gap is within this


def side_possible(team_size: int, sizes: set[int]) -> bool:
    """Whether the tickets currently in this queue could ever form a full team (e.g. in 3v3, only 2-player parties can never make 3)."""
    reach = {0}
    for _ in range(team_size):
        reach |= {r + s for r in reach for s in sizes if r + s <= team_size}
    return team_size in reach


def find_teams(
    anchor: T,
    candidates: Sequence[T],
    team_size: int,
    size_of: Callable[[T], int],
    rating_of: Callable[[T], float],
    nets_of: Callable[[T], set[str]],
) -> tuple[list[T], list[T]] | None:
    """Return (anchor's team, opposing team), or None if no match can be formed. candidates should already be sorted by rating gap to the anchor."""
    need = 2 * team_size - size_of(anchor)
    if need < 1 or size_of(anchor) > team_size:
        return None
    pool = [c for c in candidates[:MAX_CANDIDATES] if 1 <= size_of(c) <= team_size]
    best: tuple[float, list[T], list[T]] | None = None
    for evals, picked in enumerate(_subsets_summing(pool, need, size_of)):
        if evals >= MAX_EVALS:
            break
        split = _best_split(anchor, picked, team_size, size_of, rating_of, nets_of)
        if split is not None and (best is None or split[0] < best[0]):
            best = split
            if best[0] <= GOOD_GAP:
                break
    return (best[1], best[2]) if best else None


def _subsets_summing(items: Sequence[T], target: int, size_of: Callable[[T], int]) -> Iterator[list[T]]:
    """Yield, in order, subsets whose player counts sum exactly to target (earlier candidates first), pruning anything that overshoots."""
    def walk(start: int, left: int, acc: list[T]) -> Iterator[list[T]]:
        if left == 0:
            yield list(acc)
            return
        for i in range(start, len(items)):
            s = size_of(items[i])
            if s <= left:
                acc.append(items[i])
                yield from walk(i + 1, left - s, acc)
                acc.pop()
    yield from walk(0, target, [])


def _best_split(anchor, picked, team_size, size_of, rating_of, nets_of):
    """Split picked + anchor into two sides: the anchor's side fills team_size, and no network appears on both sides."""
    best = None
    for mates in _subsets_summing(picked, team_size - size_of(anchor), size_of):
        a = [anchor, *mates]
        b = [x for x in picked if not any(x is m for m in mates)]
        if _nets(a, nets_of) & _nets(b, nets_of):
            continue  # players on the same network would become opponents
        gap = abs(_avg(a, size_of, rating_of) - _avg(b, size_of, rating_of))
        if best is None or gap < best[0]:
            best = (gap, a, b)
    return best


def _nets(side, nets_of) -> set[str]:
    out: set[str] = set()
    for x in side:
        out |= nets_of(x)
    return out


def _avg(side, size_of, rating_of) -> float:
    n = sum(size_of(x) for x in side)
    return sum(rating_of(x) * size_of(x) for x in side) / n
