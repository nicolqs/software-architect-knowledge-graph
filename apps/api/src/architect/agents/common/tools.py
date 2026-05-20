"""Typed traversal toolkit for agents.

Why this layer exists: agents must NEVER emit raw Cypher. Letting an LLM
build query strings is the agent equivalent of SQL injection — one
hallucinated `MATCH (n) DETACH DELETE n` and the graph is gone. Each
helper below is a parameterized Cypher template; agents pass typed args.

All tools in this module are read-only. Write tools (`propose_node`,
`propose_edge`) land separately and route through `decision_log` so
nothing touches the live graph without a human approval step.

The helpers are exposed two ways:
- Raw async Python functions (used by tests and infra code).
- `langgraph_tools(...)` returns a list of LangChain `@tool` wrappers an
  agent can bind to its model with `model.bind_tools(tools)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from architect.graph import client as graph_client

log = structlog.get_logger()


# --- Result dataclasses --------------------------------------------------


@dataclass(slots=True)
class FunctionHit:
    qname: str
    name: str
    repo: str
    file_path: str | None
    line: int | None


@dataclass(slots=True)
class CallEdge:
    caller_qname: str
    target_qname: str
    confidence: float


@dataclass(slots=True)
class SubgraphNode:
    qname: str
    label: str


@dataclass(slots=True)
class SubgraphEdge:
    from_qname: str
    to_qname: str
    rel: str


@dataclass(slots=True)
class Subgraph:
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]


# --- Raw async functions (parameterized Cypher) --------------------------


async def find_function(*, repo: str, name: str, limit: int = 10) -> list[FunctionHit]:
    """Return functions whose simple name matches exactly (`name`), within `repo`.

    Case-sensitive. Use `last segment` semantics: methods named `greet`
    in any class match; matching is *not* against the full qname.
    """
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (fn:Function {repo: $repo, name: $name})
            RETURN fn.qname AS qname, fn.name AS name,
                   fn.file_path AS file_path, fn.line AS line
            LIMIT $limit
            """,
            repo=repo,
            name=name,
            limit=limit,
        )
        rows = await result.data()
    return [
        FunctionHit(
            qname=r["qname"],
            name=r["name"],
            repo=repo,
            file_path=r.get("file_path"),
            line=r.get("line"),
        )
        for r in rows
    ]


async def callers_of(
    *,
    repo: str,
    qname: str,
    min_confidence: float = 0.5,
    limit: int = 50,
) -> list[CallEdge]:
    """Functions that call `qname` directly (1 hop).

    Target can be a Function (regular call) or Class (constructor call) —
    both kinds of CALLS edges are surfaced.
    """
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (caller:Function {repo: $repo})-[r:CALLS]->(target {repo: $repo, qname: $qname})
            WHERE (target:Function OR target:Class)
              AND r.confidence >= $min_confidence
            RETURN caller.qname AS caller_qname,
                   target.qname AS target_qname,
                   r.confidence  AS confidence
            ORDER BY r.confidence DESC, caller.qname ASC
            LIMIT $limit
            """,
            repo=repo,
            qname=qname,
            min_confidence=min_confidence,
            limit=limit,
        )
        rows = await result.data()
    return [
        CallEdge(
            caller_qname=r["caller_qname"],
            target_qname=r["target_qname"],
            confidence=r["confidence"],
        )
        for r in rows
    ]


async def dependents_of(
    *,
    repo: str,
    module_qname: str,
    limit: int = 50,
) -> list[str]:
    """Files that IMPORT from `module_qname` directly."""
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:IMPORTS]->(m:Module {repo: $repo, qname: $module_qname})
            RETURN DISTINCT file.path AS path
            ORDER BY path ASC
            LIMIT $limit
            """,
            repo=repo,
            module_qname=module_qname,
            limit=limit,
        )
        rows = await result.data()
    return [r["path"] for r in rows]


async def subgraph_around(
    *,
    repo: str,
    qname: str,
    depth: int = 1,
    limit_per_hop: int = 25,
) -> Subgraph:
    """N-hop subgraph around a node, in either direction.

    Capped at `limit_per_hop` neighbors per hop to keep the result digestible
    for an LLM context window. Higher fan-out gets truncated.
    """
    if depth < 1 or depth > 3:
        raise ValueError("depth must be 1, 2, or 3")
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (root {repo: $repo, qname: $qname})
            CALL apoc.path.subgraphAll(root, {
                maxLevel: $depth,
                limit: $limit
            })
            YIELD nodes, relationships
            RETURN
                [n IN nodes | {
                    qname: coalesce(n.qname, n.name, '<unknown>'),
                    label: labels(n)[0]
                }] AS nodes,
                [r IN relationships | {
                    from_qname: coalesce(startNode(r).qname, startNode(r).name, '<unknown>'),
                    to_qname:   coalesce(endNode(r).qname,   endNode(r).name,   '<unknown>'),
                    rel:        type(r)
                }] AS edges
            """,
            repo=repo,
            qname=qname,
            depth=depth,
            limit=limit_per_hop * depth * 2,
        )
        record = await result.single()
    if record is None:
        return Subgraph(nodes=[], edges=[])
    nodes = [SubgraphNode(qname=n["qname"], label=n["label"]) for n in record["nodes"]]
    edges = [
        SubgraphEdge(from_qname=e["from_qname"], to_qname=e["to_qname"], rel=e["rel"])
        for e in record["edges"]
    ]
    return Subgraph(nodes=nodes, edges=edges)


# --- LangChain @tool wrappers --------------------------------------------


class _FindFunctionArgs(BaseModel):
    repo: str = Field(..., description="Repo name as stored in the graph.")
    name: str = Field(..., description="Simple function name (no module prefix). Case-sensitive.")
    limit: int = Field(10, ge=1, le=100)


class _CallersOfArgs(BaseModel):
    repo: str
    qname: str = Field(..., description="Fully-qualified name of the callee.")
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)
    limit: int = Field(50, ge=1, le=200)


class _DependentsOfArgs(BaseModel):
    repo: str
    module_qname: str = Field(..., description="Module qname (dotted for Python, slashed for TS).")
    limit: int = Field(50, ge=1, le=200)


class _SubgraphAroundArgs(BaseModel):
    repo: str
    qname: str
    depth: int = Field(1, ge=1, le=3)
    limit_per_hop: int = Field(25, ge=1, le=100)


def langgraph_tools(*, repo_default: str | None = None) -> list[StructuredTool]:
    """Return LangChain tool wrappers an agent can bind to its model.

    `repo_default` is informational only — the model still has to pass it
    explicitly. We keep tools repo-aware because most agents work over one
    repo at a time and we want the LLM to commit to which.
    """
    _ = repo_default  # reserved for v2 default-prefilling

    async def _find_function_tool(repo: str, name: str, limit: int = 10) -> list[dict[str, Any]]:
        hits = await find_function(repo=repo, name=name, limit=limit)
        return [
            {
                "qname": h.qname,
                "name": h.name,
                "file_path": h.file_path,
                "line": h.line,
            }
            for h in hits
        ]

    async def _callers_of_tool(
        repo: str, qname: str, min_confidence: float = 0.5, limit: int = 50
    ) -> list[dict[str, Any]]:
        edges = await callers_of(
            repo=repo, qname=qname, min_confidence=min_confidence, limit=limit
        )
        return [
            {"caller_qname": e.caller_qname, "confidence": e.confidence} for e in edges
        ]

    async def _dependents_of_tool(repo: str, module_qname: str, limit: int = 50) -> list[str]:
        return await dependents_of(repo=repo, module_qname=module_qname, limit=limit)

    async def _subgraph_around_tool(
        repo: str, qname: str, depth: int = 1, limit_per_hop: int = 25
    ) -> dict[str, Any]:
        sg = await subgraph_around(
            repo=repo, qname=qname, depth=depth, limit_per_hop=limit_per_hop
        )
        return {
            "nodes": [{"qname": n.qname, "label": n.label} for n in sg.nodes],
            "edges": [
                {"from": e.from_qname, "to": e.to_qname, "rel": e.rel} for e in sg.edges
            ],
        }

    return [
        StructuredTool.from_function(
            coroutine=_find_function_tool,
            name="find_function",
            description="Find a function in the graph by its simple (last-segment) name.",
            args_schema=_FindFunctionArgs,
        ),
        StructuredTool.from_function(
            coroutine=_callers_of_tool,
            name="callers_of",
            description="List functions that directly call a given function (1 hop).",
            args_schema=_CallersOfArgs,
        ),
        StructuredTool.from_function(
            coroutine=_dependents_of_tool,
            name="dependents_of",
            description="List files that IMPORT from a given module qname.",
            args_schema=_DependentsOfArgs,
        ),
        StructuredTool.from_function(
            coroutine=_subgraph_around_tool,
            name="subgraph_around",
            description="Return an N-hop subgraph (1-3 hops) around a node. Capped per-hop.",
            args_schema=_SubgraphAroundArgs,
        ),
    ]


__all__ = [
    "CallEdge",
    "FunctionHit",
    "Subgraph",
    "SubgraphEdge",
    "SubgraphNode",
    "callers_of",
    "dependents_of",
    "find_function",
    "langgraph_tools",
    "subgraph_around",
]
