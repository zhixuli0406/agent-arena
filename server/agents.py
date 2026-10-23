"""Agent standby channel: players must bring their own agent, and the agent is how a seat gets played.

Every player's agent (the reference client or the MCP bridge) keeps one SSE stream open
(GET /api/lobby/agent/stream). That stream is
- presence: queueing, readying up in a room and starting a room all require the player's agent to be online;
- dispatch: when a match starts, the seat's connection token goes to the agent here, and only here
  (the browser never receives it, so a seat can't be answered by hand from the lobby page).

Assignments are kept for a while so an agent that reconnects still gets a match that started while it was
away; clients drop duplicates by match id.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

GRACE = 20.0          # an agent still counts as online this long after its stream drops (it is probably reconnecting)
KEEP = 600.0          # undelivered/redeliverable assignments are kept this long
MAX_PER_PLAYER = 4    # assignments kept per player


@dataclass
class _Box:
    open: dict[str, int] = field(default_factory=dict)   # open streams per credential (hash)
    dead: set[str] = field(default_factory=set)          # credentials signed out while their stream was still open
    left_at: float = float("-inf")
    items: list[dict] = field(default_factory=list)
    seq: int = 0
    event: asyncio.Event | None = None


class AgentHub:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._boxes: dict[str, _Box] = {}

    def _box(self, pid: str) -> _Box:
        return self._boxes.setdefault(pid, _Box())

    def online(self, pid: str) -> bool:
        b = self._boxes.get(pid)
        if not b:
            return False
        live = any(n > 0 for cred, n in b.open.items() if cred not in b.dead)
        return live or self._clock() - b.left_at < GRACE

    def connect(self, pid: str, cred: str = "") -> None:
        b = self._box(pid)
        b.open[cred] = b.open.get(cred, 0) + 1
        b.dead.discard(cred)

    def disconnect(self, pid: str, cred: str = "") -> None:
        b = self._box(pid)
        n = b.open.get(cred, 0) - 1
        if n > 0:
            b.open[cred] = n
        else:
            b.open.pop(cred, None)
        if cred in b.dead:                   # signed out: no grace period
            if n <= 0:
                b.dead.discard(cred)
            return
        b.left_at = self._clock()

    def sign_out(self, pid: str, keep: str) -> None:
        """Every credential but `keep` was revoked: those agents are offline right away (no grace),
        and their streams wake up to notice and close."""
        b = self._box(pid)
        b.dead |= {cred for cred in b.open if cred != keep}
        b.left_at = float("-inf")
        if b.event is not None:
            b.event.set()
        b.event = None

    def assign(self, pid: str, item: dict) -> None:
        """Queue a match for this player's agent and wake its streams."""
        b = self._box(pid)
        now = self._clock()
        b.seq += 1
        b.items = [x for x in b.items if now - x["_at"] < KEEP][-(MAX_PER_PLAYER - 1):] + [{**item, "_id": b.seq, "_at": now}]
        if b.event is not None:
            b.event.set()
        b.event = None

    def pending(self, pid: str, after: int) -> list[dict]:
        now = self._clock()
        return [x for x in self._box(pid).items if x["_id"] > after and now - x["_at"] < KEEP]

    async def wait(self, pid: str, after: int, timeout: float) -> bool:
        """Wait until there is an assignment newer than `after` (True) or the timeout passes (False)."""
        if self.pending(pid, after):
            return True
        b = self._box(pid)
        if b.event is None:
            b.event = asyncio.Event()
        try:
            await asyncio.wait_for(b.event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return bool(self.pending(pid, after))

    def reap(self) -> None:
        now = self._clock()
        for pid, b in list(self._boxes.items()):
            b.items = [x for x in b.items if now - x["_at"] < KEEP]
            if not b.open and not b.items and now - b.left_at > max(GRACE, KEEP):
                self._boxes.pop(pid, None)


def public_item(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}
