"""G3 cleanup: removes arena targets/runners past their TTL and leftover isolated networks.

Stops resources from being orphaned and held after a match crashes. Can run on a schedule: python -m arena.provision.reaper

Network cleanup rules (to avoid racing with matches in progress): only delete arena networks that are expired AND have no containers attached.
- With an arena.expires label: the label decides whether it has expired.
- Unlabeled arena- networks created by older versions: decided by creation time + LEGACY_NET_TTL.
- A freshly created network with no containers yet isn't expired, so it won't be deleted by mistake; anything undecidable is kept.
A failing docker command is only recorded and doesn't stop the batch.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime

LEGACY_NET_TTL = 2 * 3600  # unlabeled old networks: expired only once created more than 2 hours ago
_DOCKER_TIMEOUT = 60


def _docker(*args: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=_DOCKER_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return (-1, "", f"{type(e).__name__}: {e}")
    return (r.returncode, r.stdout, r.stderr)


def _parse_created(value: str) -> float | None:
    """Docker's Created is RFC3339 with up to nanosecond fractions; truncate to microseconds before parsing."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$", value or "")
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = "+00:00" if m.group(3) == "Z" else m.group(3)
    try:
        return datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}").timestamp()
    except ValueError:
        return None


def network_expired(info: dict, now: float) -> bool:
    """Whether a network is safe to delete: expired and no containers attached. If undecidable, keep it (return False)."""
    if info.get("Containers"):
        return False
    labels = info.get("Labels") or {}
    if "arena.expires" in labels:
        try:
            exp = int(labels["arena.expires"])
        except (TypeError, ValueError):
            return False
        return 0 < exp < now
    created = _parse_created(str(info.get("Created", "")))
    return created is not None and created + LEGACY_NET_TTL < now


def reap(now: int | None = None) -> tuple[list[str], list[str]]:
    """Return (removed resources, error messages). Errors don't stop the batch."""
    now = now or int(time.time())
    removed: list[str] = []
    errors: list[str] = []

    rc, out, err = _docker("ps", "-aq", "--filter", "label=arena.expires")
    if rc != 0:
        errors.append(f"listing containers failed: {err.strip()[:200]}")
        out = ""
    for cid in out.split():
        rc, insp, err = _docker("inspect", cid)
        if rc != 0:
            errors.append(f"inspect {cid[:12]} failed: {err.strip()[:120]}")
            continue
        try:
            data = json.loads(insp)[0]
            exp = int(data["Config"]["Labels"].get("arena.expires", "0"))
        except (ValueError, KeyError, IndexError, TypeError):
            errors.append(f"container {cid[:12]} labels could not be parsed, skipped")
            continue
        if exp and exp < now:
            rc, _, err = _docker("rm", "-f", cid)
            if rc == 0:
                removed.append(cid[:12])
            else:
                errors.append(f"removing container {cid[:12]} failed: {err.strip()[:120]}")

    # networks after containers: only delete expired ones with no containers attached
    rc, out, err = _docker("network", "ls", "--filter", "name=arena-", "-q")
    if rc != 0:
        errors.append(f"listing networks failed: {err.strip()[:200]}")
        out = ""
    for nid in out.split():
        rc, insp, err = _docker("network", "inspect", nid)
        if rc != 0:
            errors.append(f"inspect network {nid[:12]} failed: {err.strip()[:120]}")
            continue
        try:
            info = json.loads(insp)[0]
        except (ValueError, IndexError, TypeError):
            errors.append(f"network {nid[:12]} info could not be parsed, skipped")
            continue
        if not str(info.get("Name", "")).startswith("arena-"):
            continue  # the name filter is a substring match; only handle names that really start with arena-
        if not network_expired(info, now):
            continue
        rc, _, err = _docker("network", "rm", nid)
        if rc == 0:
            removed.append(f"net:{info.get('Name', nid[:12])}")
        else:
            # if a container attached between the check and the delete (race), docker refuses; just keep it
            errors.append(f"removing network {info.get('Name', nid[:12])} failed: {err.strip()[:120]}")
    return removed, errors


def reap_expired(now: int | None = None) -> list[str]:
    """Legacy-compatible interface: returns only the removed resources."""
    return reap(now)[0]


def main() -> None:
    removed, errors = reap()
    print(f"reaped {len(removed)} expired resources: {removed}")
    for e in errors:
        print(f"[reaper error] {e}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
