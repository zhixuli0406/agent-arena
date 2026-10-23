"""Parties and team queues (2v2, 3v3), modeled on League of Legends party queue."""

from __future__ import annotations

import pytest

from server.i18n import I18nError
from server.lobby import DECLINE_COOLDOWN, READY_SECONDS, Lobby
from server.party import PARTY_MAX, PARTY_SPREAD


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make():
    clock = Clock()
    calls: list[dict] = []

    def start(mode, players, ranked=True, teams=None):
        calls.append({"mode": mode, "players": [p.id for p in players], "teams": teams, "ranked": ranked})
        return f"match-{len(calls)}", {p.id: f"tok-{p.id}" for p in players}

    return Lobby(start, clock=clock), clock, calls


def _duo(lb, ip_a="1.1.1.1", ip_b="1.1.1.1"):
    a, b = lb.register("A", ip=ip_a), lb.register("B", ip=ip_b)
    party = lb.create_party(a)
    lb.join_party(party.code, b)
    return a, b, party


def _err(fn, code):
    with pytest.raises(I18nError) as ei:
        fn()
    assert ei.value.key == code, ei.value.key


def test_party_create_join_leave_kick():
    lb, _, _ = make()
    a, b, party = _duo(lb)
    assert lb.party_of(b.id) is party and party.leader_id == a.id
    c = lb.register("C")
    _err(lambda: lb.kick_from_party(b, c.id), "leader_only")
    lb.kick_from_party(a, b.id)
    assert b.id not in party.members
    _err(lambda: lb.join_party(party.code, b), "party_kicked")
    lb.leave_party(a)
    assert party.code not in lb.parties            # last member leaves -> disbanded


def test_party_full_and_rating_spread():
    lb, _, _ = make()
    a = lb.register("A")
    party = lb.create_party(a)
    for i in range(PARTY_MAX - 1):
        lb.join_party(party.code, lb.register(f"m{i}"))
    _err(lambda: lb.join_party(party.code, lb.register("late")), "party_full")
    x, y = lb.register("X"), lb.register("Y")
    y.rating = x.rating + PARTY_SPREAD + 1
    _err(lambda: lb.join_party(lb.create_party(x).code, y), "party_spread")


def test_party_cannot_queue_ffa_or_by_member_or_too_big():
    lb, _, _ = make()
    a, b, party = _duo(lb)
    _err(lambda: lb.enqueue(a, "quiz", 2), "party_ffa")
    _err(lambda: lb.enqueue(b, "quiz", fmt="2v2"), "leader_only")
    lb.join_party(party.code, lb.register("C"))
    _err(lambda: lb.enqueue(a, "quiz", fmt="2v2"), "party_too_big")
    assert lb.enqueue(a, "quiz", fmt="3v3").members == party.members


def test_duo_vs_two_solos_same_side_everyone_accepts():
    lb, _, calls = make()
    a, b, _ = _duo(lb)
    s1, s2 = lb.register("S1", ip="2.2.2.2"), lb.register("S2", ip="3.3.3.3")
    t_duo = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    t1, t2 = lb.enqueue(s1, "quiz", fmt="2v2", ip="2.2.2.2"), lb.enqueue(s2, "quiz", fmt="2v2", ip="3.3.3.3")
    lb.tick()
    assert t_duo.status == t1.status == t2.status == "ready_check"
    view_b = lb.ticket_view(t_duo, b.id)["ready"]
    assert view_b["total"] == 4 and view_b["you_accepted"] is False
    sides = {p["id"]: p["side"] for p in view_b["players"]}
    assert sides[a.id] == sides[b.id] != sides[s1.id] == sides[s2.id]
    for t, p in ((t_duo, a), (t1, s1), (t2, s2)):
        lb.accept(t, p)
    assert not calls                                # teammate B hasn't accepted yet
    lb.accept(t_duo, b)
    assert len(calls) == 1 and calls[0]["ranked"] is True
    teams = calls[0]["teams"]
    assert teams[a.id] == teams[b.id] != teams[s1.id] == teams[s2.id]
    # each member gets their own token, not the party leader's
    assert lb.ticket_view(t_duo, b.id)["token"] == f"tok-{b.id}"
    assert lb.ticket_view(t_duo, a.id)["token"] == f"tok-{a.id}"


def test_party_member_decline_removes_party_only_decliner_cooldown():
    lb, clock, _ = make()
    a, b, _ = _duo(lb)
    s1, s2 = lb.register("S1", ip="2.2.2.2"), lb.register("S2", ip="3.3.3.3")
    t_duo = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    t1, t2 = lb.enqueue(s1, "quiz", fmt="2v2", ip="2.2.2.2"), lb.enqueue(s2, "quiz", fmt="2v2", ip="3.3.3.3")
    lb.tick()
    lb.accept(t1, s1)
    lb.decline(t_duo, b)
    assert t_duo.status == "declined"
    assert b.cooldown_until == clock.t + DECLINE_COOLDOWN and a.cooldown_until < clock.t
    assert t1.status == t2.status == "searching"     # solo players go back to the queue first


def test_ready_timeout_blames_only_member_who_did_not_accept():
    lb, clock, _ = make()
    a, b, _ = _duo(lb)
    s1, s2 = lb.register("S1", ip="2.2.2.2"), lb.register("S2", ip="3.3.3.3")
    t_duo = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    for s, ip in ((s1, "2.2.2.2"), (s2, "3.3.3.3")):
        lb.enqueue(s, "quiz", fmt="2v2", ip=ip)
    lb.tick()
    for t in list(lb.tickets.values()):
        for m in t.members:
            if m != b.id:
                lb.accept(t, lb.players[m])
    clock.t += READY_SECONDS + 1
    lb.tick()
    assert t_duo.status == "declined"
    assert b.cooldown_until > clock.t and a.cooldown_until < clock.t


def test_same_network_solos_become_teammates_not_opponents():
    lb, _, calls = make()
    home = "9.9.9.9"
    mom, kid = lb.register("Mom", ip=home), lb.register("Kid", ip=home)
    x, y = lb.register("X", ip="2.2.2.2"), lb.register("Y", ip="3.3.3.3")
    tickets = [lb.enqueue(p, "quiz", fmt="2v2", ip=ip)
               for p, ip in ((mom, home), (kid, home), (x, "2.2.2.2"), (y, "3.3.3.3"))]
    lb.tick()
    assert all(t.status == "ready_check" for t in tickets)
    for t in tickets:
        lb.accept(t)
    teams = calls[0]["teams"]
    assert teams[mom.id] == teams[kid.id] != teams[x.id]


def test_two_same_network_parties_never_face_each_other():
    lb, _, _ = make()
    a, b, _ = _duo(lb)
    c, d, _ = _duo(lb)                               # another 2-player party on the same network
    t1 = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    t2 = lb.enqueue(c, "quiz", fmt="2v2", ip="1.1.1.1")
    lb.tick()
    assert t1.status == t2.status == "searching"


def test_leaving_party_cancels_party_ticket_without_cooldown():
    lb, clock, _ = make()
    a, b, _ = _duo(lb)
    t = lb.enqueue(a, "quiz", fmt="2v2")
    _err(lambda: lb.join_party(lb.party_of(a.id).code, lb.register("late")), "party_queued")
    lb.leave_party(b)
    assert t.status == "cancelled" and a.cooldown_until < clock.t and b.cooldown_until < clock.t


def test_party_and_room_are_exclusive():
    lb, _, _ = make()
    a, b, party = _duo(lb)
    _err(lambda: lb.create_room(a, "quiz"), "in_party")
    c = lb.register("C")
    room = lb.create_room(c, "quiz")
    _err(lambda: lb.join_room(room.code, b), "in_party")
    _err(lambda: lb.create_party(c), "busy")


def test_team_queue_stats_count_players():
    lb, _, _ = make()
    a, _, _ = _duo(lb)
    lb.enqueue(a, "quiz", fmt="2v2")
    lb.enqueue(lb.register("S"), "task", fmt="3v3")
    st = lb.stats()
    assert st["queues"] == {"quiz:2v2": 2, "task:3v3": 1} and st["parties"] == 1


def test_no_free_dodge_during_ready_check():
    # Leaving or kicking after seeing the opponents = a free dodge; always blocked during ready check. To get out, decline (and take the cooldown)
    lb, _, _ = make()
    a, b, _ = _duo(lb)
    s1, s2 = lb.register("S1", ip="2.2.2.2"), lb.register("S2", ip="3.3.3.3")
    t = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    lb.enqueue(s1, "quiz", fmt="2v2", ip="2.2.2.2")
    lb.enqueue(s2, "quiz", fmt="2v2", ip="3.3.3.3")
    lb.tick()
    assert t.status == "ready_check"
    _err(lambda: lb.leave_party(b), "party_in_check")
    _err(lambda: lb.kick_from_party(a, b.id), "party_in_check")


def test_member_request_ip_counts_for_same_network():
    # The IPs members actually send requests from count toward same-network checks (not just the leader's, not just at sign-up)
    lb, _, _ = make()
    alt = lb.register("Alt", ip="5.5.5.5")
    stranger = lb.register("Stranger", ip="6.6.6.6")
    party = lb.create_party(stranger)
    lb.join_party(party.code, alt)
    lb.auth(alt.id, alt.secret, ip="7.7.7.7")                 # the alt now connects from the attacker's home
    me = lb.register("Me", ip="7.7.7.7")
    other = lb.register("Other", ip="8.8.8.8")
    lb.enqueue(stranger, "quiz", fmt="2v2", ip="6.6.6.6")
    lb.enqueue(me, "quiz", fmt="2v2", ip="7.7.7.7")
    lb.enqueue(other, "quiz", fmt="2v2", ip="8.8.8.8")
    lb.tick()
    # The only possible split is Alt's party vs Me + Other, but Alt and Me share a network -> no match
    assert all(t.status == "searching" for t in lb.tickets.values())


def test_declined_view_shows_viewers_own_cooldown():
    lb, clock, _ = make()
    a, b, _ = _duo(lb)
    s1, s2 = lb.register("S1", ip="2.2.2.2"), lb.register("S2", ip="3.3.3.3")
    t = lb.enqueue(a, "quiz", fmt="2v2", ip="1.1.1.1")
    lb.enqueue(s1, "quiz", fmt="2v2", ip="2.2.2.2")
    lb.enqueue(s2, "quiz", fmt="2v2", ip="3.3.3.3")
    lb.tick()
    lb.decline(t, b)
    assert lb.ticket_view(t, b.id)["cooldown"] > 0 and lb.ticket_view(t, a.id)["cooldown"] == 0


def test_full_lobby_disbands_guest_parties():
    import server.lobby as L
    lb, _, _ = make()
    old = L.MAX_PLAYERS
    L.MAX_PLAYERS = 6
    try:
        for i in range(3):                                     # flood accounts pair up into parties to hold spots
            x, y = lb.register(f"x{i}"), lb.register(f"y{i}")
            lb.join_party(lb.create_party(x).code, y)
        lb.register("newcomer")                                # capacity full: still gets in
        assert len(lb.parties) < 3
    finally:
        L.MAX_PLAYERS = old


def test_matchmaking_tick_stays_bounded_under_worst_case():
    # Measured in review: 500 mutually conflicting 3v3 tickets took 6+ seconds per tick before the fix (stalling the whole event loop)
    import time
    lb, clock, _ = make()
    for i in range(500):
        p = lb.register(f"n{i}", ip="9.9.9.9")
        lb.enqueue(p, "quiz", ip=f"10.0.{i // 250}.{i % 250}", fmt="3v3")
    clock.t += 100
    for _ in range(3):
        t0 = time.perf_counter()
        lb.tick()
        assert time.perf_counter() - t0 < 0.3
