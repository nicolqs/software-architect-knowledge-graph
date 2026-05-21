"""GET /graph/* — read-only graph routes the UI consumes."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from architect.agents.common.tools import subgraph_around
from architect.graph import client as graph_client

log = structlog.get_logger()
router = APIRouter(prefix="/graph", tags=["graph"])


class GraphNode(BaseModel):
    qname: str
    label: str


class GraphEdge(BaseModel):
    from_qname: str
    to_qname: str
    rel: str


class SubgraphResponse(BaseModel):
    repo: str
    qname: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@router.get("/subgraph", response_model=SubgraphResponse)
async def subgraph(
    repo: str = Query(...),
    qname: str = Query(...),
    depth: int = Query(1, ge=1, le=3),
) -> SubgraphResponse:
    sg = await subgraph_around(repo=repo, qname=qname, depth=depth)
    if not sg.nodes:
        raise HTTPException(404, f"No node {qname!r} found in repo {repo!r}")
    return SubgraphResponse(
        repo=repo,
        qname=qname,
        depth=depth,
        nodes=[GraphNode(qname=n.qname, label=n.label) for n in sg.nodes],
        edges=[
            GraphEdge(from_qname=e.from_qname, to_qname=e.to_qname, rel=e.rel)
            for e in sg.edges
        ],
    )


class RepoSummary(BaseModel):
    name: str
    files: int
    functions: int
    classes: int
    modules: int


@router.get("/repos", response_model=list[RepoSummary])
async def repos() -> list[RepoSummary]:
    """List ingested repos with simple counts. Used by the UI repo picker."""
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (r:Repo)
            OPTIONAL MATCH (r)-[:HAS_FILE]->(f:File)
            WITH r, count(DISTINCT f) AS files
            OPTIONAL MATCH (fn:Function {repo: r.name})
            WITH r, files, count(DISTINCT fn) AS functions
            OPTIONAL MATCH (c:Class {repo: r.name})
            WITH r, files, functions, count(DISTINCT c) AS classes
            OPTIONAL MATCH (m:Module {repo: r.name})
            WHERE NOT m.qname STARTS WITH 'external::'
            RETURN r.name AS name, files, functions, classes,
                   count(DISTINCT m) AS modules
            ORDER BY name
            """
        )
        rows = await result.data()
    return [RepoSummary(**r) for r in rows]


class QnameSuggestion(BaseModel):
    qname: str
    label: str
    callers: int


@router.get("/qnames", response_model=list[QnameSuggestion])
async def qnames(
    repo: str = Query(...),
    q: str = Query("", description="Substring filter, case-insensitive."),
    limit: int = Query(40, ge=1, le=200),
) -> list[QnameSuggestion]:
    """Top Function / Class qnames in `repo` matching `q`, sorted by fan-in.

    Powers the Graph viewer's autocomplete + default-qname picker so users
    don't need to know the qname convention to see something useful.
    """
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (n {repo: $repo})
            WHERE (n:Function OR n:Class)
              AND ($q = '' OR toLower(n.qname) CONTAINS toLower($q))
              AND NOT n.qname STARTS WITH 'external::'
            OPTIONAL MATCH (c)-[:CALLS]->(n)
            WITH n, count(c) AS callers
            RETURN n.qname AS qname, labels(n)[0] AS label, callers
            ORDER BY callers DESC, n.qname
            LIMIT $limit
            """,
            repo=repo,
            q=q,
            limit=limit,
        )
        rows = await result.data()
    return [
        QnameSuggestion(qname=r["qname"], label=r["label"], callers=r["callers"])
        for r in rows
    ]
