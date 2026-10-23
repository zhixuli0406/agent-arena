"""Rebuild a lobby state / ladder file from scratch, keeping only fields we expect.

Used in CI before state leaves the isolated server account (and on restore): the
server could be compromised, so we never copy its bytes as-is into the public
`data` branch. Parse, validate every field, write canonical JSON; anything else is dropped.

    python3 -I infra/sanitize_state.py lobby_state.json <in> <out>
    python3 -I infra/sanitize_state.py ladder.json <in> <out>
Exit 1 when the file is not a usable state file at all.
"""

from __future__ import annotations

import json
import math
import re
import sys

MAX_BYTES = 2_000_000
MAX_ENTRIES = 20_000
PLAYER_ID = re.compile(r"^p_[0-9a-f]{6,32}$")
SECRET_HASH = re.compile(r"^[0-9a-f]{64}$")
AXES = ("model", "prompt", "team")


def _rating(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return round(f, 2) if math.isfinite(f) and 0 <= f <= 10_000 else None


def _text(v: object, limit: int) -> str | None:
    if not isinstance(v, str) or len(v) > limit:
        return None
    return "".join(ch for ch in v if ch.isprintable())


def lobby_state(data: object) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("players"), list):
        raise ValueError("not a lobby state")
    players = []
    for d in data["players"][:MAX_ENTRIES]:
        if not isinstance(d, dict):
            continue
        pid, h = d.get("id"), d.get("secret_hash")
        rating, name, agent = _rating(d.get("rating")), _text(d.get("name"), 24), _text(d.get("agent", ""), 40)
        games = d.get("games")
        if not (isinstance(pid, str) and PLAYER_ID.match(pid) and isinstance(h, str) and SECRET_HASH.match(h)):
            continue
        if rating is None or name is None or agent is None:
            continue
        if isinstance(games, bool) or not isinstance(games, int) or not 0 <= games <= 10_000_000:
            continue
        players.append({"id": pid, "name": name, "rating": rating, "games": games,
                        "agent": agent, "secret_hash": h})
    return {"version": 1, "players": players}


def ladder(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("not a ladder")
    out: dict[str, dict[str, float]] = {}
    for axis in AXES:
        table = data.get(axis, {})
        clean: dict[str, float] = {}
        if isinstance(table, dict):
            for k, v in list(table.items())[:MAX_ENTRIES]:
                key, r = _text(k, 80), _rating(v)
                if key and r is not None:
                    clean[key] = r
        out[axis] = clean
    return out


KINDS = {"lobby_state.json": lobby_state, "ladder.json": ladder}


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in KINDS:
        print(f"usage: {argv[0]} lobby_state.json|ladder.json <in> <out>", file=sys.stderr)
        return 2
    kind, src, dst = argv[1:]
    try:
        with open(src, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("too large")
        clean = KINDS[kind](json.loads(raw.decode("utf-8")))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        print(f"rejected {kind}: {e}", file=sys.stderr)
        return 1
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
