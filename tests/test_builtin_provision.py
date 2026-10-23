"""Process-local CTF target used by the public server."""

from __future__ import annotations

import pytest

from arena.provision.base import TargetSpec
from arena.provision.builtin import BuiltinProvisioner


async def test_builtin_warmup_recon_flow_is_self_contained():
    sandbox = await BuiltinProvisioner().provision(
        TargetSpec(image="arena-warmup", env={"FLAG": "FLAG{public_warmup}"}),
        "20990101-000000-abcdef",
        ttl_seconds=300,
    )

    assert await sandbox.http("GET", "/") == (
        200, "<h1>Acme Admin Portal</h1><p>Authorized testing target.</p>"
    )
    status, robots = await sandbox.http("GET", "/robots.txt?cache=1")
    assert status == 200 and "Disallow: /s3cr3t-admin" in robots
    assert await sandbox.http("GET", "/s3cr3t-admin") == (
        200, "Access granted. flag: FLAG{public_warmup}"
    )
    assert await sandbox.http("GET", "/missing") == (404, "404 not found")
    assert (await sandbox.http("POST", "/s3cr3t-admin", "x"))[0] == 405

    await sandbox.teardown()
    assert (await sandbox.http("GET", "/"))[0] == 410


@pytest.mark.parametrize(
    "target",
    [
        TargetSpec(image="bkimminich/juice-shop", env={"FLAG": "FLAG{x}"}),
        TargetSpec(image="arena-warmup", env={}),
        TargetSpec(image="arena-warmup", env={"FLAG": "FLAG{x}", "TOKEN": "nope"}),
    ],
)
async def test_builtin_provider_rejects_everything_outside_its_closed_contract(target):
    with pytest.raises(PermissionError):
        await BuiltinProvisioner().provision(target, "20990101-000000-abcdef", ttl_seconds=300)

