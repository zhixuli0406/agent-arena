"""remote adapter: round alignment, state broadcast and reconnects for player-supplied agents."""

from __future__ import annotations

import asyncio

from arena.adapters.remote import RemoteAdapter, drop_slot, get_slot
from arena.types import AgentSpec, Observation


async def _wait_question(slot):
    while slot.current is None:
        await slot.wait_change(slot.version, 1)
    return slot.current


async def test_stale_action_from_other_round_is_discarded():
    ad = RemoteAdapter(AgentSpec(id="p", adapter="remote", params={"token": "tk-sync"}))
    slot = get_slot("tk-sync")
    await slot.actions.put((99, "遲到的舊答案"))

    async def player():
        obs = await _wait_question(slot)
        await slot.actions.put((obs.round, "東京"))

    t = asyncio.create_task(player())
    act = await asyncio.wait_for(ad.act(Observation(round=1, task="日本首都？")), timeout=2)
    await t
    assert act.content == "東京"
    assert slot.current is None                  # answered: a reconnect won't resend this question
    drop_slot("tk-sync")


async def test_unrounded_action_accepted():
    ad = RemoteAdapter(AgentSpec(id="p", adapter="remote", params={"token": "tk-any"}))
    slot = get_slot("tk-any")
    await slot.actions.put((None, "391", "I reduced the multiplication before submitting."))
    act = await asyncio.wait_for(ad.act(Observation(round=3, task="17*23")), timeout=2)
    assert act.content == "391"
    assert act.meta["public_summary"] == "I reduced the multiplication before submitting."
    drop_slot("tk-any")


async def test_broadcast_wakes_every_connection_and_end_is_visible_to_all():
    # regression: the old design delivered through a queue, so a stale connection could swallow the question or end signal and a new connection would wait forever
    slot = get_slot("tk-bc")
    seen = slot.version
    watchers = [asyncio.create_task(slot.wait_change(seen, 2)) for _ in range(3)]
    await asyncio.sleep(0)
    slot.publish(Observation(round=1, task="x"))
    assert all(await asyncio.gather(*watchers))
    late = slot.version
    slot.finish()
    assert slot.ended and slot.current is None
    assert await slot.wait_change(late, 0.1)     # a connection made after the end learns about it immediately
    drop_slot("tk-bc")


async def test_wait_change_times_out_for_heartbeat():
    slot = get_slot("tk-hb")
    assert await slot.wait_change(slot.version, 0.05) is False
    drop_slot("tk-hb")
