"""Remote adapter: players bring their own agents and connect through one shared entry point. The arena holds zero keys and is vendor-neutral.

Players run their own agent on their side (their own keys, prompts, tools, or even a human typing) and connect
to the arena with a connect token: receive a question, send back an answer. The engine runs no model on their
behalf and holds no vendor keys; how the answer is produced is entirely up to the player.

Delivery is "state broadcast", not "queue consumption": the slot only keeps the current question, a version number
and whether the match is over. Every connection reads the same state and sends when the version changes, so a
reconnect, two windows open at once, or a stale old connection can't "steal" a question or the end signal.
Answers carry a round number and only answers for the current round are accepted.
"""

from __future__ import annotations

import asyncio

from ..types import Action, AgentSpec, Observation, Usage
from .base import Adapter, AdapterUnavailable


ACTION_QUEUE_MAX = 8
PUBLIC_SUMMARY_MAX_CHARS = 280


class RemoteSlot:
    def __init__(self) -> None:
        self.current: Observation | None = None    # question currently awaiting an answer
        self.ended: bool = False                   # match has ended
        self.version: int = 0                      # +1 on every state change
        self.connections: int = 0
        # (round | None, content, public_summary); bounded so answer floods cannot exhaust memory.
        self.actions: asyncio.Queue = asyncio.Queue(maxsize=ACTION_QUEUE_MAX)
        self._changed = asyncio.Event()

    def publish(self, obs: Observation) -> None:
        self.current = obs
        self._bump()

    def finish(self) -> None:
        self.ended = True
        self.current = None
        self._bump()

    def _bump(self) -> None:
        self.version += 1
        ev, self._changed = self._changed, asyncio.Event()
        ev.set()                                    # wake every waiting connection

    async def wait_change(self, seen: int, timeout: float) -> bool:
        """Wait until the state version differs from seen; return False on timeout (so the caller can send a heartbeat)."""
        if self.version != seen:
            return True
        ev = self._changed
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


_REGISTRY: dict[str, RemoteSlot] = {}


def get_slot(token: str) -> RemoteSlot:
    slot = _REGISTRY.get(token)
    if slot is None:
        slot = RemoteSlot()
        _REGISTRY[token] = slot
    return slot


def drop_slot(token: str) -> None:
    _REGISTRY.pop(token, None)


class RemoteAdapter(Adapter):
    # Player-supplied agents run on the player's side: the engine side has no tools, doesn't touch the host and holds no keys.
    is_host_actor = False

    def __init__(self, spec: AgentSpec):
        super().__init__(spec)
        self.token = spec.params.get("token")
        if not self.token:
            raise AdapterUnavailable("remote adapter needs params.token (issued by the server when the match starts)")
        get_slot(self.token)  # create the slot up front so players can connect and wait before the match starts

    async def act(self, obs: Observation) -> Action:
        slot = get_slot(self.token)
        slot.publish(obs)
        try:
            while True:  # the engine wraps this wait in its per-step timeout
                item = await slot.actions.get()
                rnd, content = item[:2]
                public_summary = item[2] if len(item) > 2 else ""  # accept old in-process producers
                if rnd is None or rnd == obs.round:
                    meta = {"public_summary": public_summary} if public_summary else {}
                    return Action(content=content, usage=Usage(), meta=meta)
                # late or resent answers for other rounds: discard
        finally:
            if slot.current is obs:
                slot.current = None                 # answered or timed out: a reconnect won't resend this question
