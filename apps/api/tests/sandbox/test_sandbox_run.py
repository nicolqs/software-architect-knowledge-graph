"""End-to-end integration: actually invoke `docker run` in the sandbox.

Skipped when Docker isn't reachable. Three checks:
1. Happy path: script returns 0 with expected stdout.
2. Network is off — `wget google.com` must fail (DNS or connect).
3. Timeout fires: a script that sleeps longer than the timeout is killed.
"""

from __future__ import annotations

import pytest

from architect.sandbox.runner import SandboxRequest, docker_available
from architect.sandbox.runner import run as sandbox_run


async def _docker_up() -> bool:
    return await docker_available()


@pytest.fixture(autouse=True)
async def _require_docker() -> None:
    if not await _docker_up():
        pytest.skip("docker not available in this test environment")


async def test_happy_path_echo() -> None:
    res = await sandbox_run(
        SandboxRequest(image="alpine:3.20", script="echo hello-sandbox")
    )
    assert res.exit_code == 0
    assert "hello-sandbox" in res.stdout
    assert res.timed_out is False


async def test_network_is_off() -> None:
    # wget against an unreachable host should fail fast inside the sandbox.
    # We don't rely on a specific error message — only that the exit is non-zero.
    res = await sandbox_run(
        SandboxRequest(
            image="alpine:3.20",
            script="wget -q -T 3 -O - https://example.com || echo NETWORK_BLOCKED",
            timeout_s=15,
        )
    )
    assert "NETWORK_BLOCKED" in res.stdout
    assert res.exit_code == 0  # the `||` makes the overall script succeed


async def test_timeout_fires() -> None:
    res = await sandbox_run(
        SandboxRequest(image="alpine:3.20", script="sleep 30", timeout_s=2)
    )
    assert res.timed_out is True
    assert res.duration_s < 10  # quickly killed, not after 30
