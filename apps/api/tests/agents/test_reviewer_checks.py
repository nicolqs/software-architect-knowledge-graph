"""End-to-end integration: reviewer checks run against the live graph.

Skipped when Neo4j isn't reachable. Doesn't assert specific finding counts
(those depend on which repo state is loaded) — only that the runner returns
a list and respects the changed_files filter.
"""

from __future__ import annotations

import pytest

from architect.agents.reviewer.checks import run_checks
from architect.config import Settings
from architect.graph import client as graph_client


def _neo4j_available() -> bool:
    import socket
    s = Settings()
    # The URI is `bolt://host:port` — parse off the port.
    uri = s.neo4j_uri.removeprefix("bolt://").removeprefix("neo4j://")
    host, _, port = uri.partition(":")
    try:
        with socket.create_connection((host or "localhost", int(port or "7687")), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _neo4j_available(), reason="live Neo4j not reachable"
)


@pytest.fixture(autouse=True)
async def _driver():
    settings = Settings()
    graph_client.init_driver(settings)
    yield
    await graph_client.close_driver()


async def test_empty_changed_files_yields_no_findings() -> None:
    findings = await run_checks("architect-self", [])
    assert findings == []


async def test_runs_against_existing_repo() -> None:
    # We don't assert specific findings; we just check the runner returns
    # a list and doesn't raise. The integration smoke is in the eval harness.
    result = await run_checks(
        "architect-self",
        ["apps/api/src/architect/ingest/writer.py"],
    )
    assert isinstance(result, list)
    # Severity values are well-formed when findings exist.
    for f in result:
        assert f.severity in {"critical", "important", "advisory"}
