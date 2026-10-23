"""Transparent resident House agents: profiles, answers and matchmaking fallback."""

from __future__ import annotations

import random

from arena.modes.quiz import grade
from arena.modes.task import check_output
from server.house import HOUSE_FILL_DELAY, HOUSE_NETWORK, HouseManager, build_profiles, scripted_answers
from server.lobby import Lobby
from server.question_bank import pick


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_lobby():
    clock = Clock()
    starts: list[dict] = []

    def start(mode, players, ranked=True, **kwargs):
        starts.append({"mode": mode, "players": [p.id for p in players], "ranked": ranked})
        return f"match-{len(starts)}", {p.id: f"token-{p.id}" for p in players if not p.house}

    return Lobby(start, clock=clock), clock, starts


def test_profiles_are_randomized_transparent_and_cover_strength_levels():
    profiles = build_profiles(4, random.Random(7))

    assert len(profiles) == 4
    assert len({p.name for p in profiles}) == 4
    assert all(p.name.startswith("[House] ") for p in profiles)
    assert all(p.model.startswith("House Logic ") and p.prompt for p in profiles)
    assert {p.strength for p in profiles} >= {"rookie", "steady", "elite"}
    assert min(p.accuracy for p in profiles) < max(p.accuracy for p in profiles)
    assert min(p.delay for p in profiles) < max(p.delay for p in profiles)


def test_scripted_answers_respect_profile_accuracy_for_quiz_and_task():
    strong = build_profiles(1, random.Random(1))[0]
    strong.accuracy = 1.0
    quiz = pick("quiz", n=5, rng=random.Random(2))
    q_answers = scripted_answers(quiz, strong, random.Random(3))
    assert all(grade(question, answer) for question, answer in zip(quiz["questions"], q_answers))

    task = pick("task", n=6, rng=random.Random(4))
    t_answers = scripted_answers(task, strong, random.Random(5))
    assert all(check_output(item["check"], answer) for item, answer in zip(task["tasks"], t_answers))

    weak = build_profiles(1, random.Random(6))[0]
    weak.accuracy = 0.0
    assert scripted_answers(quiz, weak, random.Random(7)) == ["?"] * len(quiz["questions"])


def test_house_agents_never_match_each_other_and_fill_after_delay():
    lobby, clock, starts = make_lobby()
    bots = [lobby.register(f"[House] B{i}", house=True) for i in range(2)]
    bot_tickets = [lobby.enqueue(bot, "quiz", ip=HOUSE_NETWORK) for bot in bots]
    lobby.tick()
    assert all(t.status == "searching" for t in bot_tickets)
    assert not lobby.proposals

    human = lobby.register("Human")
    human_ticket = lobby.enqueue(human, "quiz", ip="198.51.100.10")
    lobby.tick()
    assert human_ticket.status == "searching"

    clock.t += HOUSE_FILL_DELAY + 0.1
    lobby.tick()
    assert human_ticket.status == "ready_check"
    chosen = next(iter(lobby.proposals.values()))
    assert sum(lobby.players[p].house for p in lobby._proposal_players(chosen)) == 1

    lobby.accept(human_ticket)
    house_ticket = next(lobby.tickets[tid] for tid in chosen.ticket_ids if tid != human_ticket.id)
    lobby.accept(house_ticket)
    assert len(starts) == 1
    assert starts[0]["mode"] == "quiz" and starts[0]["ranked"] is False
    assert set(starts[0]["players"]) == {bots[0].id, human.id}
    assert not human_ticket.ranked and not house_ticket.ranked


def test_two_humans_are_matched_before_house_fallback():
    lobby, _, _ = make_lobby()
    house = lobby.register("[House] Waiting", house=True)
    house_ticket = lobby.enqueue(house, "quiz", ip=HOUSE_NETWORK)
    humans = [lobby.register("Alice"), lobby.register("Bob")]
    human_tickets = [lobby.enqueue(p, "quiz", ip=f"198.51.100.{i + 1}") for i, p in enumerate(humans)]

    lobby.tick()

    assert house_ticket.status == "searching"
    assert all(t.status == "ready_check" for t in human_tickets)
    proposal = next(iter(lobby.proposals.values()))
    assert all(not lobby.players[p].house for p in lobby._proposal_players(proposal))


def test_house_manager_registers_agents_queues_modes_and_auto_accepts():
    lobby, clock, _ = make_lobby()
    showcases: list[list[str]] = []
    manager = HouseManager(
        lobby,
        count=4,
        seed_matches=2,
        rng=random.Random(9),
        clock=clock,
        live_match_of=lambda _pid: None,
        start_showcase=lambda profiles: showcases.append([p.name for p in profiles]) or True,
    )

    manager.tick()

    players = [p for p in lobby.players.values() if p.house]
    assert len(players) == 4
    assert {t.mode for t in lobby.tickets.values()} == {"quiz", "task"}
    assert lobby.stats()["house_agents"] == 4
    assert lobby.stats()["online"] == 0
    assert showcases and len(showcases[0]) == 2

    human = lobby.register("Human")
    human_ticket = lobby.enqueue(human, "quiz", ip="198.51.100.20")
    clock.t += HOUSE_FILL_DELAY + 0.1
    lobby.tick()
    manager.tick()
    proposal = lobby._proposal_of(human_ticket)
    house_ids = {p.id for p in players}
    assert proposal.accepted & house_ids
