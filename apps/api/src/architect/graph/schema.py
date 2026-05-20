"""Neo4j schema: labels, constraints, indexes.

All statements are idempotent (`IF NOT EXISTS`). `apply()` is called at
startup and from the ingest CLI.

See `docs/graph-schema.md` for the conceptual model. Confidence scores on
`CALLS` edges follow: 1.0 static intra-file, 0.7 cross-file static import,
0.3 inferred dynamic.
"""

from __future__ import annotations

import structlog

from architect.graph import client as graph_client

log = structlog.get_logger()

# Each entry is a single Cypher statement. We avoid multi-statement strings so
# any single failure surfaces with a clear error.
_CONSTRAINTS: tuple[str, ...] = (
    # Repo identity
    "CREATE CONSTRAINT repo_name_unique IF NOT EXISTS FOR (r:Repo) REQUIRE r.name IS UNIQUE",
    # Files keyed by (repo, path)
    "CREATE CONSTRAINT file_repo_path_unique IF NOT EXISTS FOR (f:File) REQUIRE (f.repo, f.path) IS UNIQUE",
    # Modules keyed by (repo, qname)
    "CREATE CONSTRAINT module_qname_unique IF NOT EXISTS FOR (m:Module) REQUIRE (m.repo, m.qname) IS UNIQUE",
    # Functions / Classes keyed by (repo, qname)
    "CREATE CONSTRAINT function_qname_unique IF NOT EXISTS FOR (fn:Function) REQUIRE (fn.repo, fn.qname) IS UNIQUE",
    "CREATE CONSTRAINT class_qname_unique IF NOT EXISTS FOR (c:Class) REQUIRE (c.repo, c.qname) IS UNIQUE",
    # External callables (unresolved imports, stdlib functions). One node per qname.
    "CREATE CONSTRAINT external_qname_unique IF NOT EXISTS FOR (e:External) REQUIRE (e.repo, e.qname) IS UNIQUE",
)

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX file_path_idx IF NOT EXISTS FOR (f:File) ON (f.path)",
    "CREATE INDEX function_name_idx IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE INDEX class_name_idx IF NOT EXISTS FOR (c:Class) ON (c.name)",
    "CREATE INDEX module_qname_idx IF NOT EXISTS FOR (m:Module) ON (m.qname)",
)


async def apply() -> None:
    """Apply constraints + indexes. Safe to call repeatedly."""
    async with graph_client.session() as session:
        for stmt in _CONSTRAINTS:
            await session.run(stmt)
        for stmt in _INDEXES:
            await session.run(stmt)
    log.info("neo4j_schema_applied", constraints=len(_CONSTRAINTS), indexes=len(_INDEXES))


async def drop_repo(repo_name: str) -> None:
    """Hard-delete all nodes for a repo. Used by `ingest --reset`.

    Parameterized — never accept a Cypher-formatted repo name.
    """
    async with graph_client.session() as session:
        await session.run(
            """
            MATCH (n {repo: $repo})
            DETACH DELETE n
            """,
            repo=repo_name,
        )
    log.info("repo_dropped", repo=repo_name)
