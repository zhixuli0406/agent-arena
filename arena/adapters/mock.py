"""Mock adapter: scripted output for offline tests and control groups. Connects to no external service."""

from __future__ import annotations

import asyncio

from ..types import Action, AgentSpec, Observation, Usage
from .base import Adapter


class MockAdapter(Adapter):
    def __init__(self, spec: AgentSpec):
        super().__init__(spec)
        self._answers = list(spec.params.get("answers", []))
        self._public_summaries = list(spec.params.get("public_summaries", []))
        self._reply = str(spec.params.get("reply", ""))
        self._delay = float(spec.params.get("delay", 0.0))
        self._i = 0

    async def act(self, obs: Observation) -> Action:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._i < len(self._answers):
            content = str(self._answers[self._i])
            self._i += 1
        else:
            content = self._reply
        summary = str(self._public_summaries[self._i - 1]) if 0 < self._i <= len(self._public_summaries) else ""
        meta = {"public_summary": summary} if summary else {}
        return Action(content=content, usage=Usage(output_tokens=len(content.split())), meta=meta)
