"""Provisioner registry and factory. Switching clouds only touches the provider; the engine and modes stay untouched."""

from __future__ import annotations

from .base import Provisioner, Sandbox, TargetSpec
from .builtin import BuiltinProvisioner
from .cloudrun import CloudRunProvisioner
from .freehost import FreeHostProvisioner
from .local import LocalDockerProvisioner

REGISTRY: dict[str, type[Provisioner]] = {
    "builtin": BuiltinProvisioner,          # inert process-local warmup target; safe for the public server
    "local": LocalDockerProvisioner,       # local Docker, isolated and private (real vulnerable images go here)
    "freehost": FreeHostProvisioner,       # free hosting (Cloudflare tunnel), benign self targets only
    "cloudrun": CloudRunProvisioner,       # GCP Cloud Run (not entirely free, optional)
}


def build_provisioner(name: str) -> Provisioner:
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown provisioner: {name} (available: {', '.join(REGISTRY)})")
    return cls()


__all__ = ["Provisioner", "Sandbox", "TargetSpec", "build_provisioner", "REGISTRY"]
