"""Integration tests for the propose_node/propose_edge write path.

Verifies that agent-staged proposals land in decision_log with the right
shape and status, and that the review/apply flow flips status correctly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from psycopg_pool import AsyncConnectionPool

from architect.agents.common.proposals import (
    list_proposals,
    propose_edge,
    propose_node,
    review_proposal,
)
from architect.config import Settings


def _postgres_available() -> bool:
    import socket
    s = Settings()
    try:
        with socket.create_connection((s.postgres_host, s.postgres_port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="live Postgres not reachable"
)


@pytest.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool]:
    settings = Settings()
    p = AsyncConnectionPool(conninfo=settings.postgres_dsn, min_size=1, max_size=2, open=False)
    await p.open()
    yield p
    # Clean up the rows this test created. The test agent name 'test-architect'
    # is unique enough that we won't trample real data.
    async with p.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM decision_log WHERE agent = 'test-architect'")
    await p.close()


async def test_propose_node_writes_row(pool: AsyncConnectionPool) -> None:
    proposal_id = await propose_node(
        pool=pool,
        agent="test-architect",
        thread_id="t-1",
        repo="demo",
        label="Service",
        qname="ChatService",
        props={"layer": "domain"},
    )
    assert proposal_id > 0

    proposals = await list_proposals(pool=pool, agent="test-architect", status="proposed")
    assert len(proposals) == 1
    p = proposals[0]
    assert p.action == "propose_node"
    assert p.repo == "demo"
    assert p.target_qname == "ChatService"
    assert p.props["label"] == "Service"
    assert p.props["qname"] == "ChatService"
    assert p.props["props"] == {"layer": "domain"}


async def test_propose_edge_writes_row(pool: AsyncConnectionPool) -> None:
    await propose_edge(
        pool=pool,
        agent="test-architect",
        thread_id="t-1",
        repo="demo",
        from_qname="ChatService",
        to_qname="AuthService",
        rel_type="DEPENDS_ON",
    )
    proposals = await list_proposals(pool=pool, agent="test-architect", status="proposed")
    edge = next((p for p in proposals if p.action == "propose_edge"), None)
    assert edge is not None
    assert edge.props["from_qname"] == "ChatService"
    assert edge.props["to_qname"] == "AuthService"
    assert edge.props["rel_type"] == "DEPENDS_ON"


async def test_review_proposal_flips_status(pool: AsyncConnectionPool) -> None:
    pid = await propose_node(
        pool=pool, agent="test-architect", thread_id=None,
        repo="demo", label="Service", qname="DraftService",
    )
    await review_proposal(pool=pool, decision_id=pid, status="rejected", reviewer="qa@x")
    proposals = await list_proposals(pool=pool, agent="test-architect", status="rejected")
    assert any(p.id == pid for p in proposals)
