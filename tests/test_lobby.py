"""Online lobby: matchmaking queues, ready check, custom rooms (fake clock, deterministic)."""

from __future__ import annotations

import pytest

from server.lobby import (BASE_WINDOW, DECLINE_COOLDOWN, GUEST_TTL, MAX_TICKETS_PER_IP, READY_SECONDS,
                          ROOM_CODE_LEN, WIDEN_PER_SEC, Lobby, LobbyError, clean_text)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make():
    clock = Clock()
    calls: list[tuple[str, list[str]]] = []
    ranked: list[bool] = []

    def start(mode, players, ranked_flag=True, **kw):
        ranked.append(kw.get("ranked", ranked_flag))
        calls.append((mode, [p.id for p in players]))
        return f"match-{len(calls)}", {p.id: f"tok-{p.id}" for p in players}

    start.ranked = ranked

    return Lobby(start, clock=clock), clock, calls


def test_same_rating_pairs_and_ready_check_launches():
    lb, clock, calls = make()
    a, b = lb.register("Alice"), lb.register("Bob")
    ta, tb = lb.enqueue(a, "quiz"), lb.enqueue(b, "quiz")
    lb.tick()
    assert ta.status == tb.status == "ready_check"
    lb.accept(ta)
    assert not calls                      # not everyone has accepted yet
    lb.accept(tb)
    assert calls == [("quiz", [a.id, b.id])]
    assert ta.status == tb.status == "confirmed"
    assert ta.token == f"tok-{a.id}" and tb.token == f"tok-{b.id}"
    assert lb.ticket_view(ta)["match_id"] == "match-1"
    assert lb.ticket_view(ta)["ranked"] is True and lb._start.ranked == [True]   # matchmade games count on the ladder


def test_rating_window_widens_with_wait():
    lb, clock, _ = make()
    a, b = lb.register("A"), lb.register("B")
    a.rating, b.rating = 1500, 1500 + BASE_WINDOW + 100   # initial rating gap exceeds the window
    ta, tb = lb.enqueue(a, "quiz"), lb.enqueue(b, "quiz")
    lb.tick()
    assert ta.status == "searching"
    clock.t += 100 / WIDEN_PER_SEC + 1                     # wait until the window widens
    lb.tick()
    assert ta.status == tb.status == "ready_check"


def test_decline_cooldown_and_priority_requeue():
    lb, clock, _ = make()
    a, b = lb.register("A"), lb.register("B")
    ta = lb.enqueue(a, "quiz")
    clock.t += 5
    tb = lb.enqueue(b, "quiz")
    lb.tick()
    lb.accept(ta)
    lb.decline(tb)
    assert tb.status == "declined"
    assert ta.status == "searching" and ta.enqueued_at == 1000.0   # original queue time is kept
    with pytest.raises(LobbyError) as e:
        lb.enqueue(b, "quiz")
    assert e.value.code == 429
    clock.t += DECLINE_COOLDOWN + 1
    assert lb.enqueue(b, "quiz").status == "searching"


def test_ready_check_timeout_treated_as_decline():
    lb, clock, calls = make()
    a, b = lb.register("A"), lb.register("B")
    ta, tb = lb.enqueue(a, "quiz"), lb.enqueue(b, "quiz")
    lb.tick()
    lb.accept(ta)
    clock.t += READY_SECONDS + 0.5
    lb.tick()
    assert tb.status == "declined"
    assert ta.status in ("searching", "ready_check")   # those who accepted go back to the queue (may be matched again right away)
    assert not calls


def test_three_player_queue_needs_three():
    lb, clock, calls = make()
    ps = [lb.register(f"P{i}") for i in range(3)]
    ts = [lb.enqueue(p, "task", size=3) for p in ps[:2]]
    lb.tick()
    assert all(t.status == "searching" for t in ts)
    ts.append(lb.enqueue(ps[2], "task", size=3))
    lb.tick()
    assert all(t.status == "ready_check" for t in ts)
    for t in ts:
        lb.accept(t)
    assert calls and len(calls[0][1]) == 3


def test_cancel_and_no_double_queue():
    lb, clock, _ = make()
    a = lb.register("A")
    t = lb.enqueue(a, "quiz")
    with pytest.raises(LobbyError):
        lb.enqueue(a, "quiz")
    lb.cancel(t)
    assert t.status == "cancelled"
    assert lb.enqueue(a, "quiz").status == "searching"


def test_room_ready_up_host_start_and_token_privacy():
    lb, clock, calls = make()
    host, guest = lb.register("Host"), lb.register("Guest")
    r = lb.create_room(host, "quiz", size=4)
    lb.join_room(r.code.lower(), guest)                    # room codes are case-insensitive
    with pytest.raises(LobbyError):
        lb.start_room(r.code, guest)                       # only the host can start
    with pytest.raises(LobbyError):
        lb.start_room(r.code, host)                        # guest isn't ready yet
    lb.set_ready(r.code, guest, True)
    lb.start_room(r.code, host)
    assert r.status == "started" and calls == [("quiz", [host.id, guest.id])]
    assert lb._start.ranked == [False] and lb.room_view(r)["ranked"] is False   # custom rooms don't count on the ladder
    assert len(r.code) == ROOM_CODE_LEN
    assert lb.room_view(r, guest.id)["token"] == f"tok-{guest.id}"
    assert "token" not in lb.room_view(r, None)           # nobody but the owner sees the token


def test_room_host_transfer_and_cleanup():
    lb, clock, _ = make()
    a, b = lb.register("A"), lb.register("B")
    r = lb.create_room(a, "quiz")
    lb.join_room(r.code, b)
    lb.leave_room(r.code, a)
    assert r.host_id == b.id
    lb.leave_room(r.code, b)
    assert r.code not in lb.rooms


def test_auth_and_stats():
    lb, clock, _ = make()
    a = lb.register("A")
    with pytest.raises(LobbyError):
        lb.auth(a.id, "wrong")
    assert lb.auth(a.id, a.secret) is a
    lb.enqueue(a, "quiz")
    s = lb.stats()
    assert s["online"] == 1 and s["searching"] == 1 and s["queues"] == {"quiz:2": 1}


def test_persistence_stores_only_secret_hash_and_restores_auth():
    lb, clock, _ = make()
    a, guest = lb.register("Alice"), lb.register("Guest")
    lb.apply_rating(a.id, 16)                      # only players who have played are saved
    data = lb.dump()
    assert [p["id"] for p in data["players"]] == [a.id]
    assert a.secret not in str(data)               # plaintext secret never hits disk
    lb2, _, _ = make()
    assert lb2.restore(data) == 1
    p = lb2.auth(a.id, a.secret)                   # after restart the original secret still logs in
    assert p.rating == 1516 and p.games == 1
    with pytest.raises(LobbyError):
        lb2.auth(a.id, "wrong")
    assert lb2.restore({"players": [{"id": "evil", "secret_hash": "x"}]}) == 0   # bad data is rejected


def test_room_details_members_only_and_kick():
    lb, clock, _ = make()
    host, guest, outsider = lb.register("H"), lb.register("G"), lb.register("O")
    r = lb.create_room(host, "quiz")
    lb.join_room(r.code, guest)
    with pytest.raises(LobbyError) as e:
        lb.member_room(r.code, outsider)
    assert e.value.code == 403
    with pytest.raises(LobbyError):
        lb.kick(r.code, guest, host.id)                    # only the host can kick
    lb.kick(r.code, host, guest.id)
    assert guest.id not in r.members
    with pytest.raises(LobbyError) as e:
        lb.join_room(r.code, guest)                        # a kicked player can't rejoin
    assert e.value.key == "kicked"


def test_ip_ticket_cap_and_error_translation():
    lb, clock, _ = make()
    ps = [lb.register(f"P{i}") for i in range(MAX_TICKETS_PER_IP + 1)]
    for p in ps[:-1]:
        lb.enqueue(p, "quiz", ip="1.2.3.4")
    with pytest.raises(LobbyError) as e:
        lb.enqueue(ps[-1], "quiz", ip="1.2.3.4")
    assert e.value.code == 429
    assert "network" in e.value.text("en") and "ネットワーク" in e.value.text("ja")
    assert lb.enqueue(ps[-1], "quiz", ip="5.6.7.8").status == "searching"


def test_idle_guests_reaped_but_players_with_games_kept():
    lb, clock, _ = make()
    guest, vet, queued = lb.register("guest"), lb.register("vet"), lb.register("queued")
    lb.apply_rating(vet.id, 5)
    lb.enqueue(queued, "quiz", size=3)
    clock.t += GUEST_TTL + 1
    lb.tick()
    assert guest.id not in lb.players
    assert vet.id in lb.players and queued.id in lb.players


def test_matching_scales_and_pairs_closest_rating():
    lb, clock, calls = make()
    ps = [lb.register(f"P{i}") for i in range(400)]
    for i, p in enumerate(ps):
        p.rating = 1000 + (i * 7919 % 400) * 5            # spread-out ratings
        lb.enqueue(p, "quiz")
    lb.tick()
    props = list(lb.proposals.values())
    assert len(props) >= 190                               # greedy first-queued-first-matched: nearly all get matched; a few wait for the window to widen
    for prop in props:
        a, b = (lb.players[lb.tickets[t].player_id].rating for t in prop.ticket_ids)
        assert abs(a - b) <= BASE_WINDOW


def test_clean_text_strips_controls_and_bidi():
    assert clean_text("A\u202eB\x00C\n  D", 24) == "ABC D"     # bidi override and NUL removed, newline becomes a space
    assert len(clean_text("x" * 100, 24)) == 24


def test_ranked_queue_never_pairs_same_network():
    lb, clock, calls = make()
    a, b, c = lb.register("A"), lb.register("B"), lb.register("C")
    ta, tb = lb.enqueue(a, "quiz", ip="9.9.9.9"), lb.enqueue(b, "quiz", ip="9.9.9.9")
    lb.tick()
    assert ta.status == tb.status == "searching"          # two accounts on the same network aren't matched together
    tc = lb.enqueue(c, "quiz", ip="8.8.8.8")
    lb.tick()
    assert tc.status == "ready_check" and ta.status == "ready_check" and tb.status == "searching"


def test_full_lobby_evicts_oldest_idle_guests_instead_of_locking_out(monkeypatch):
    import server.lobby as lobby_mod
    monkeypatch.setattr(lobby_mod, "MAX_PLAYERS", 200)
    lb, clock, _ = make()
    first = lb.register("first")
    for i in range(199):
        clock.t += 1
        lb.register(f"flood{i}")
    clock.t += 1
    late = lb.register("late")                       # still gets in when capacity is full
    assert late.id in lb.players and first.id not in lb.players


def test_loopback_clients_can_pair_for_local_dev():
    lb, clock, _ = make()
    a, b = lb.register("A"), lb.register("B")
    ta, tb = lb.enqueue(a, "quiz", ip="127.0.0.1"), lb.enqueue(b, "quiz", ip="127.0.0.1")
    lb.tick()
    assert ta.status == tb.status == "ready_check"


def test_loopback_exempt_from_ip_ticket_cap():
    # In local development every client is 127.0.0.1: the per-IP ticket cap doesn't apply (on the public server the IP comes from Cloudflare)
    lb, _, _ = make()
    for i in range(MAX_TICKETS_PER_IP + 2):
        lb.enqueue(lb.register(f"L{i}"), "quiz", ip="127.0.0.1")


def test_full_lobby_evicts_crowded_ip_guests_first(monkeypatch):
    import server.lobby as Lmod
    lb, clock, _ = make()
    monkeypatch.setattr(Lmod, "MAX_PLAYERS", 6)
    legit = lb.register("Legit", ip="1.1.1.1")              # oldest idle guest, alone on its IP
    clock.t += 10
    flood = [lb.register(f"f{i}", ip="6.6.6.6") for i in range(5)]
    lb.register("newcomer", ip="2.2.2.2")
    assert legit.id in lb.players                            # flood accounts went first
    assert sum(1 for f in flood if f.id in lb.players) < 5
