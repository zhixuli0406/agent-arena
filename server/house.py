"""Transparent resident House opponents for low-traffic public lobbies.

House agents use the deterministic mock adapter and are always labelled. They do not
claim to be third-party models, and matches involving them are never rated.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .lobby import HOUSE_FILL_DELAY, Lobby, LobbyError, Player

HOUSE_NETWORK = "192.0.2.254"  # RFC 5737 documentation address; all House agents share it
SHOWCASE_GAP = 8.0

_NAMES = ["Aster", "Bolt", "Cipher", "Drift", "Echo", "Flux", "Glint", "Halo", "Iris", "Jolt"]
_PROMPTS = [
    "Solve carefully, then return only the requested final form.",
    "Prefer a quick direct calculation and verify once before answering.",
    "Extract constraints first; keep the final response minimal.",
    "Use pattern recognition, but reject the first guess if it fails a sanity check.",
    "Prioritize exact formatting and machine-checkable output.",
    "Work from the supplied evidence only and avoid extra commentary.",
]
_LEVELS = {
    "rookie": {"model": "House Logic S", "accuracy": 0.48, "delay": 1.25, "rating": 1250.0},
    "steady": {"model": "House Logic M", "accuracy": 0.72, "delay": 0.85, "rating": 1500.0},
    "elite": {"model": "House Logic L", "accuracy": 0.92, "delay": 0.45, "rating": 1780.0},
}


@dataclass
class HouseProfile:
    name: str
    model: str
    prompt: str
    strength: str
    accuracy: float
    delay: float
    rating: float
    mode: str

    def to_config(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> "HouseProfile":
        return cls(**{k: value[k] for k in cls.__dataclass_fields__})


def build_profiles(count: int, rng: random.Random | None = None) -> list[HouseProfile]:
    rng = rng or random.Random()
    count = max(0, min(int(count), len(_NAMES)))
    required = ["rookie", "steady", "elite"]
    levels = [required[i] if i < len(required) else rng.choice(required) for i in range(count)]
    rng.shuffle(levels)
    modes = (["quiz", "task"] * ((count + 1) // 2))[:count]
    rng.shuffle(modes)
    profiles: list[HouseProfile] = []
    for name, strength, mode in zip(rng.sample(_NAMES, count), levels, modes):
        base = _LEVELS[strength]
        profiles.append(HouseProfile(
            name=f"[House] {name}",
            model=f"{base['model']}-{rng.choice(('1', '2', '3'))}",
            prompt=rng.choice(_PROMPTS),
            strength=strength,
            accuracy=max(0.05, min(0.98, float(base["accuracy"]) + rng.uniform(-0.04, 0.04))),
            delay=max(0.15, float(base["delay"]) + rng.uniform(-0.12, 0.12)),
            rating=float(base["rating"]) + rng.randint(-35, 35),
            mode=mode,
        ))
    return profiles


def _task_answer(check: dict[str, Any]) -> str:
    kind = check.get("kind")
    if kind in ("exact", "choice", "contains", "numeric"):
        value = check.get("value", "")
        return str(value[0] if isinstance(value, list) else value)
    if kind == "regex":
        return re.sub(r"\\[bBAZz]", "", str(check.get("pattern", ""))).replace("\\-", "-")
    if kind == "contains_all":
        return " ".join(str(v[0] if isinstance(v, (list, tuple)) else v) for v in check.get("values", []))
    if kind == "contains_any":
        values = check.get("values", [])
        return str(values[0]) if values else "answer"
    if kind == "json_set":
        return json.dumps(check.get("values", []), ensure_ascii=False)
    if kind == "json_fields":
        data = {k: "value" for k in check.get("keys", [])}
        data.update(check.get("fields", {}))
        return json.dumps(data, ensure_ascii=False)
    if kind == "json_keys":
        keys = check.get("keys", [])
        if keys:
            return json.dumps({k: "value" for k in keys}, ensure_ascii=False)
        return json.dumps(["item"] * max(1, int(check.get("min_items", 1))), ensure_ascii=False)
    if kind == "label":
        return str(check.get("label", "neutral"))
    if kind == "min_words":
        return " ".join(["word"] * int(check.get("n", 1)))
    return "answer"


def scripted_answers(mode_config: dict[str, Any], profile: HouseProfile,
                     rng: random.Random | None = None) -> list[str]:
    rng = rng or random.Random()
    if "questions" in mode_config:
        correct = [q["answer"][0] if isinstance(q["answer"], list) else q["answer"]
                   for q in mode_config["questions"]]
    else:
        correct = [_task_answer(t["check"]) for t in mode_config.get("tasks", [])]
    return [str(answer) if rng.random() < profile.accuracy else "?" for answer in correct]


class HouseManager:
    def __init__(self, lobby: Lobby, *, count: int, seed_matches: int,
                 rng: random.Random | None = None, clock: Callable[[], float],
                 live_match_of: Callable[[str], str | None],
                 start_showcase: Callable[[list[HouseProfile]], bool]) -> None:
        self.lobby = lobby
        self.count = max(0, min(int(count), 8))
        self.seed_matches = max(0, min(int(seed_matches), 6))
        self.rng = rng or random.Random()
        self.clock = clock
        self.live_match_of = live_match_of
        self.start_showcase = start_showcase
        self.profiles: list[HouseProfile] = []
        self.players: dict[str, Player] = {}
        self.showcases_started = 0
        self.next_showcase_at = 0.0

    def _start(self) -> None:
        self.profiles = build_profiles(self.count, self.rng)
        for profile in self.profiles:
            player = self.lobby.register(profile.name, profile.model, ip=HOUSE_NETWORK,
                                         house=True, house_config=profile.to_config())
            player.rating = profile.rating
            self.players[player.id] = player

    def tick(self) -> None:
        if self.count and not self.profiles:
            self._start()
        now = self.clock()
        profile_by_name = {p.name: p for p in self.profiles}
        for player in self.players.values():
            player.last_seen = now
            if self.lobby.active_ticket(player.id) is None and self.live_match_of(player.id) is None:
                try:
                    self.lobby.enqueue(player, profile_by_name[player.name].mode, ip=HOUSE_NETWORK)
                except LobbyError:
                    pass
        # House agents always accept their ready checks; humans still make their own choice.
        for prop in list(self.lobby.proposals.values()):
            for pid in self.lobby._proposal_players(prop):
                player = self.lobby.players[pid]
                if player.house and prop.id in self.lobby.proposals and pid not in prop.accepted:
                    ticket = next(t for t in self.lobby.tickets.values()
                                  if t.proposal_id == prop.id and pid in t.members)
                    self.lobby.accept(ticket, player)
        if (self.showcases_started < self.seed_matches and len(self.profiles) >= 2
                and now >= self.next_showcase_at):
            pair = self.rng.sample(self.profiles, 2)
            if self.start_showcase(pair):
                self.showcases_started += 1
                self.next_showcase_at = now + SHOWCASE_GAP
