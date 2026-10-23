"""Public transcript projection for security matches.

The on-disk transcript is private match evidence. CTF observations, actions,
request paths, and target responses can contain a live flag, so the spectator
stream must construct events from an explicit allowlist.
"""

from __future__ import annotations

import json


def public_faults(mode: str, details: list[str]) -> list[str]:
    """Keep CTF failure counts without exposing exception or agent output text."""
    return ["Details withheld"] * len(details) if mode == "ctf" else details


def public_ctf_event(raw: str) -> str | None:
    """Return a safe CTF spectator event, or omit an unknown event entirely."""
    try:
        event = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(event, dict):
        return None

    kind = event.get("type")
    if kind not in {"match_start", "action", "agent_error", "request", "solve",
                    "submit_wrong", "result", "teams"}:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        data = {}
    safe = {k: event[k] for k in ("type", "round", "agent", "ts") if k in event}

    if kind == "match_start":
        agents = data.get("agents")
        safe["data"] = {
            "mode": "ctf",
            "agents": [
                {key: agent[key] for key in ("id", "model", "team", "prompt_author") if key in agent}
                for agent in agents if isinstance(agent, dict)
            ] if isinstance(agents, list) else [],
        }
    elif kind == "request":
        safe["data"] = {key: data[key] for key in ("method", "status") if key in data}
    elif kind == "solve":
        safe["data"] = {key: data[key] for key in ("first", "round") if key in data}
    elif kind == "submit_wrong":
        safe["data"] = {"correct": False}
    elif kind == "result":
        safe["data"] = {key: data[key] for key in ("scores", "ranking", "status") if key in data}
    elif kind == "teams":
        safe["data"] = {key: data[key] for key in ("members", "team_scores", "team_ranking") if key in data}
    else:
        safe["data"] = {}
    return json.dumps(safe, ensure_ascii=False)
