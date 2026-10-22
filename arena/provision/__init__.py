"""配置器註冊表與工廠。換雲端只動 provider，引擎與模式不動。"""

from __future__ import annotations

from .base import Provisioner, Sandbox, TargetSpec
from .cloudrun import CloudRunProvisioner
from .local import LocalDockerProvisioner

REGISTRY: dict[str, type[Provisioner]] = {
    "local": LocalDockerProvisioner,
    "cloudrun": CloudRunProvisioner,
}


def build_provisioner(name: str) -> Provisioner:
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"未知配置器：{name}（可用：{', '.join(REGISTRY)}）")
    return cls()


__all__ = ["Provisioner", "Sandbox", "TargetSpec", "build_provisioner", "REGISTRY"]
