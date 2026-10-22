"""JSONL 留痕。每個事件一行，失敗事件也顯式寫入，絕不靜默吞掉。

transcript 視為敏感產物（含完整靶機回應與 exploit 流量），以 0600 建立。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from types import TracebackType
from typing import Any


class Transcript:
    def __init__(self, path: str):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        self._f = os.fdopen(fd, "w", encoding="utf-8")

    def write(self, event: Any) -> None:
        d = asdict(event) if is_dataclass(event) else event
        self._f.write(json.dumps(d, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()

    def __enter__(self) -> "Transcript":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.close()
