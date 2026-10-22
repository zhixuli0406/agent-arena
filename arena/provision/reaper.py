"""G3 清掃：移除超過 TTL 的 arena 靶機/runner 與殘留隔離網路。

防止某局崩潰後資源變孤兒持續佔用。可定時跑：python -m arena.provision.reaper
"""

from __future__ import annotations

import json
import subprocess
import time


def reap_expired(now: int | None = None) -> list[str]:
    now = now or int(time.time())
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=arena.expires"],
        capture_output=True, text=True,
    ).stdout.split()
    removed: list[str] = []
    for cid in listed:
        insp = subprocess.run(["docker", "inspect", cid], capture_output=True, text=True).stdout
        try:
            data = json.loads(insp)[0]
            exp = int(data["Config"]["Labels"].get("arena.expires", "0"))
        except (ValueError, KeyError, IndexError):
            continue
        if exp and exp < now:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
            removed.append(cid[:12])
    # 殘留的 arena 隔離網路（使用中者會刪除失敗，忽略）
    nets = subprocess.run(
        ["docker", "network", "ls", "--filter", "name=arena-", "-q"], capture_output=True, text=True
    ).stdout.split()
    for nid in nets:
        subprocess.run(["docker", "network", "rm", nid], capture_output=True)
    return removed


def main() -> None:
    removed = reap_expired()
    print(f"reaped {len(removed)} 個逾期容器：{removed}")


if __name__ == "__main__":
    main()
