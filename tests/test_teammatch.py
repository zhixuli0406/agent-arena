"""Team matchmaking algorithm: parties stay together, same network never opposes, team averages stay close."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.teammatch import find_teams


@dataclass(frozen=True)
class G:
    name: str
    size: int = 1
    rating: float = 1500.0
    nets: frozenset = field(default_factory=frozenset)


def _find(anchor, cands, team_size=2):
    return find_teams(anchor, cands, team_size, lambda g: g.size, lambda g: g.rating, lambda g: set(g.nets))


def _names(side):
    return sorted(g.name for g in side)


def test_party_of_two_stays_together_vs_two_solos():
    duo = G("duo", 2)
    r = _find(duo, [G("s1"), G("s2")])
    assert r is not None
    a, b = r
    assert _names(a) == ["duo"] and _names(b) == ["s1", "s2"]


def test_not_enough_players():
    assert _find(G("s"), [G("t")]) is None
    assert _find(G("duo", 2), [G("trio", 3)]) is None     # a 3-player party doesn't fit in 2v2


def test_balances_average_rating():
    a, b = _find(G("x", rating=1800), [G("y", rating=1790), G("z", rating=1210), G("w", rating=1200)])
    # most balanced: 1800+1200 vs 1790+1210
    assert _names(a) == ["w", "x"] and _names(b) == ["y", "z"]


def test_same_network_never_opponents_but_can_be_teammates():
    home = frozenset({"1.2.3.4"})
    a, b = _find(G("mom", nets=home), [G("kid", nets=home), G("s1"), G("s2")])
    assert {"mom", "kid"} <= set(_names(a))                # same network -> must be teammates


def test_same_network_impossible_split_returns_none():
    home = frozenset({"1.2.3.4"})
    # Both 2-player parties come from the same network: any split makes them opponents
    assert _find(G("d1", 2, nets=home), [G("d2", 2, nets=home)]) is None


def test_three_v_three_mixed_party_sizes():
    a, b = _find(G("trio", 3), [G("duo", 2), G("s1"), G("s2")], team_size=3)
    assert _names(a) == ["trio"]
    assert sorted(_names(b)) == ["duo", "s1"] or sorted(_names(b)) == ["duo", "s2"]
