"""Write-side tools: agents propose graph mutations into `decision_log`.

The plan's load-bearing safety property is that no agent ever writes
directly to the live graph. Every proposed mutation lands here as
`status='proposed'`; a human (UI lands in M4) flips it to
`approved`/`rejected`; only then does an applier touch Neo4j.

The store/applier split keeps the agent path Neo4j-free and the writer
path human-gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import structlog
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from architect.graph import client as graph_client

log = structlog.get_logger()

Action = Literal["propose_node", "propose_edge"]
Status = Literal["proposed", "approved", "rejected", "applied"]


@dataclass(slots=True)
class Proposal:
    id: int
    agent: str
    action: Action
    repo: str | None
    target_qname: str | None
    props: dict[str, Any]
    status: Status


async def propose_node(
    *,
    pool: AsyncConnectionPool,
    agent: str,
    thread_id: str | None,
    repo: str,
    label: str,
    qname: str,
    props: dict[str, Any] | None = None,
) -> int:
    """Stage a node proposal. Returns the decision_log row id."""
    payload = {"label": label, "qname": qname, "props": props or {}}
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO decision_log (agent, thread_id, action, repo, target_qname, props, status)
            VALUES (%s, %s, 'propose_node', %s, %s, %s, 'proposed')
            RETURNING id
            """,
            (agent, thread_id, repo, qname, Json(payload)),
        )
        row = await cur.fetchone()
    assert row is not None
    log.info("propose_node", id=row[0], agent=agent, label=label, qname=qname)
    return int(row[0])


async def propose_edge(
    *,
    pool: AsyncConnectionPool,
    agent: str,
    thread_id: str | None,
    repo: str,
    from_qname: str,
    to_qname: str,
    rel_type: str,
    props: dict[str, Any] | None = None,
) -> int:
    """Stage an edge proposal. Returns the decision_log row id."""
    payload = {
        "from_qname": from_qname,
        "to_qname": to_qname,
        "rel_type": rel_type,
        "props": props or {},
    }
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO decision_log (agent, thread_id, action, repo, target_qname, props, status)
            VALUES (%s, %s, 'propose_edge', %s, %s, %s, 'proposed')
            RETURNING id
            """,
            (agent, thread_id, repo, f"{from_qname}->{to_qname}", Json(payload)),
        )
        row = await cur.fetchone()
    assert row is not None
    log.info("propose_edge", id=row[0], agent=agent, rel=rel_type)
    return int(row[0])


async def list_proposals(
    *,
    pool: AsyncConnectionPool,
    status: Status | None = None,
    repo: str | None = None,
    agent: str | None = None,
    limit: int = 100,
) -> list[Proposal]:
    where: list[str] = []
    params: list[Any] = []
    if status is not None:
        where.append("status = %s")
        params.append(status)
    if repo is not None:
        where.append("repo = %s")
        params.append(repo)
    if agent is not None:
        where.append("agent = %s")
        params.append(agent)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, agent, action, repo, target_qname, props, status "
        f"FROM decision_log{where_sql} ORDER BY id DESC LIMIT %s"
    )
    params.append(limit)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [
        Proposal(
            id=r[0],
            agent=r[1],
            action=r[2],
            repo=r[3],
            target_qname=r[4],
            props=r[5] if isinstance(r[5], dict) else {},
            status=r[6],
        )
        for r in rows
    ]


async def review_proposal(
    *,
    pool: AsyncConnectionPool,
    decision_id: int,
    status: Literal["approved", "rejected"],
    reviewer: str,
) -> None:
    """Set status to approved or rejected. Apply happens separately."""
    if status not in ("approved", "rejected"):
        raise ValueError("status must be 'approved' or 'rejected'")
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE decision_log
            SET status = %s, reviewed_at = now(), reviewed_by = %s
            WHERE id = %s AND status = 'proposed'
            """,
            (status, reviewer, decision_id),
        )


async def apply_proposal(*, pool: AsyncConnectionPool, decision_id: int) -> bool:
    """Apply an approved proposal to Neo4j. Marks the row as 'applied'.

    Returns True if applied, False if not found or not in 'approved' status.
    Uses parameterized Cypher — never string-formats the proposal contents.
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT action, repo, props FROM decision_log WHERE id = %s AND status = 'approved'",
            (decision_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return False
    action, repo, props = row
    payload: dict[str, Any] = props if isinstance(props, dict) else {}

    if action == "propose_node":
        label = payload["label"]
        # Whitelist allowed labels to keep this safe even though the action
        # came from a human-approved row.
        if label not in {"Service", "API", "DBTable", "Feature", "InfraComponent"}:
            raise ValueError(f"Refusing to create node with label {label!r}")
        async with graph_client.session() as s:
            await s.run(
                f"MERGE (n:{label} {{repo: $repo, qname: $qname}}) SET n += $props",
                repo=repo,
                qname=payload["qname"],
                props=payload.get("props", {}),
            )
    elif action == "propose_edge":
        rel = payload["rel_type"]
        if rel not in {"DEPENDS_ON", "OWNS", "CALLS", "WRITES_TO", "READS_FROM", "DEPLOYED_ON"}:
            raise ValueError(f"Refusing to create edge of type {rel!r}")
        async with graph_client.session() as s:
            await s.run(
                f"""
                MATCH (a {{repo: $repo, qname: $from_qname}})
                MATCH (b {{repo: $repo, qname: $to_qname}})
                MERGE (a)-[r:{rel}]->(b)
                SET r += $props
                """,
                repo=repo,
                from_qname=payload["from_qname"],
                to_qname=payload["to_qname"],
                props=payload.get("props", {}),
            )
    else:
        raise ValueError(f"Unknown action: {action!r}")

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE decision_log SET status = 'applied' WHERE id = %s", (decision_id,)
        )
    return True


__all__ = [
    "Action",
    "Proposal",
    "Status",
    "apply_proposal",
    "list_proposals",
    "propose_edge",
    "propose_node",
    "review_proposal",
]
