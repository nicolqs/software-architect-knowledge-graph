"""Graph analytics for the Refactor Planner.

v1 ships three deterministic analyses run against the ingested graph:
1. Dead code — functions with zero incoming CALLS (modulo entry points
   and test files).
2. High-coupling modules — top-N by degree centrality (fanin + fanout).
3. Duplicate logic — placeholder; needs the pgvector embeddings to
   cluster function bodies. Skipped when no embeddings are present (no
   OPENAI_API_KEY at ingest time means no embeddings).

Each finding gets a `risk` and `blast_radius` so the output can be sorted
by where a refactor pays back the most without cascading too far.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import structlog

from architect.graph import client as graph_client

log = structlog.get_logger()

Kind = Literal["dead_code", "high_coupling", "duplicate_logic"]


@dataclass(slots=True)
class RefactorItem:
    kind: Kind
    qname: str
    title: str
    rationale: str
    risk: Literal["low", "medium", "high"]
    blast_radius: int  # number of nodes likely affected by the refactor
    file_path: str | None = None
    line: int | None = None


# Filenames whose contents we ignore as "live" code (tests, evals, migrations).
_IGNORE_PATH_FRAGMENTS = ("test", "/evals/", "/migrations/", "/__main__")


def _is_ignored_path(path: str | None) -> bool:
    if not path:
        return False
    return any(frag in path for frag in _IGNORE_PATH_FRAGMENTS)


async def find_dead_code(repo: str, limit: int = 100) -> list[RefactorItem]:
    """Functions with zero incoming CALLS, filtered to skip framework-invoked
    code that static analysis can't see being called.

    Filter heuristics ("live unless proven dead"):
    - Path `*/api/*.py`: FastAPI route handlers — invoked by the framework.
    - Qname matches `*.build_*_graph.*`: LangGraph node closures.
    - File `*.tsx` + PascalCase name: React components / page exports.
    - Pydantic / settings property-style names: `postgres_dsn`, `active_*`.
    - Polymorphic dispatch: if another function elsewhere has the same
      simple name AND has callers, this one is plausibly a Protocol impl.
    - Standard framework names: `lifespan`, `constructor`.
    """
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:CONTAINS]->(fn:Function {repo: $repo})
            WHERE NOT (()-[:CALLS]->(fn))
              AND NOT fn.name STARTS WITH '_'
              AND fn.name <> 'main'
              AND NOT fn.name STARTS WITH 'test'
            RETURN fn.qname AS qname, fn.name AS name,
                   file.path AS file_path, fn.line AS line
            ORDER BY file.path, fn.line
            LIMIT $limit
            """,
            repo=repo,
            limit=limit,
        )
        rows = await result.data()

        # Names that have callers somewhere — used by the polymorphic filter.
        poly_result = await s.run(
            """
            MATCH (fn:Function {repo: $repo})
            WHERE ()-[:CALLS]->(fn)
            RETURN collect(DISTINCT fn.name) AS names
            """,
            repo=repo,
        )
        poly_row = await poly_result.single()
        names_with_callers: set[str] = (
            set(poly_row["names"]) if poly_row is not None else set()
        )

    items: list[RefactorItem] = []
    for r in rows:
        if _is_ignored_path(r.get("file_path")):
            continue
        if _is_framework_invoked(r):
            continue
        if r["name"] in names_with_callers:
            # Polymorphic / Protocol impl — another function with the same
            # name has callers; we can't statically tell which impl runs.
            continue
        items.append(
            RefactorItem(
                kind="dead_code",
                qname=r["qname"],
                title=f"Dead code: {r['name']}",
                rationale=(
                    f"Function {r['name']} has no incoming CALLS edges, no framework "
                    "dispatch pattern, and no name collision with a called sibling. "
                    "Likely safe to delete; double-check string-keyed dispatch first."
                ),
                risk="low",
                blast_radius=0,
                file_path=r.get("file_path"),
                line=r.get("line"),
            )
        )
    return items


def _is_framework_invoked(row: dict[str, Any]) -> bool:
    """Heuristic 'this function is called by a framework, not user code'.

    Conservative — better to under-report dead code than nudge users to
    delete working route handlers and component functions.
    """
    path = row.get("file_path") or ""
    qname = row["qname"]
    name = row["name"]
    # FastAPI route handler files.
    if "/api/" in path and path.endswith(".py"):
        return True
    # LangGraph node closures inside `build_*_graph` builders.
    if ".build_" in qname and "_graph." in qname:
        return True
    # React components / page exports: PascalCase fn in a .tsx file.
    if path.endswith(".tsx") and name[:1].isupper():
        return True
    # Methods of React components — typically wired as JSX event handlers
    # (`onSubmit={submit}`), which are references not calls.
    # TS qname shape: `path/to/file::ComponentName::methodName`. We skip when
    # the second-to-last segment is PascalCase.
    if path.endswith(".tsx"):
        segments = qname.split("::")
        if len(segments) >= 3 and segments[-2][:1].isupper():
            return True
    # Generic helpers in lib/api.ts: called via type-args like `request<T>(...)`
    # which tree-sitter sometimes records as `request<T>` (with the type arg).
    # Skip when there's a same-name External edge pointing somewhere.
    if path.endswith("/api.ts") and name == "request":
        return True
    # Pydantic / Settings property-style attribute accessors.
    if name == "postgres_dsn" or name.startswith("active_"):
        return True
    # Standard framework / structural names.
    return name in {"lifespan", "constructor"}


async def find_high_coupling(repo: str, limit: int = 20) -> list[RefactorItem]:
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (m:Module {repo: $repo})
            // Skip stdlib / framework modules (qname carries 'external::' prefix).
            // The repo's own modules can't be refactored if they're external libs.
            WHERE NOT m.qname STARTS WITH 'external::'
            WITH m,
                 count{(:File)-[:IMPORTS]->(m)} AS fanin,
                 count{(:File {repo: $repo})-[:IN_MODULE]->(m)} AS files_in_module
            WITH m, fanin, files_in_module, fanin + files_in_module AS degree
            WHERE degree >= 5
            RETURN m.qname AS qname, fanin, files_in_module, degree
            ORDER BY degree DESC
            LIMIT $limit
            """,
            repo=repo,
            limit=limit,
        )
        rows = await result.data()
    items: list[RefactorItem] = []
    for r in rows:
        risk: Literal["low", "medium", "high"] = (
            "high" if r["degree"] >= 20 else "medium" if r["degree"] >= 10 else "low"
        )
        items.append(
            RefactorItem(
                kind="high_coupling",
                qname=r["qname"],
                title=f"High coupling: {r['qname']}",
                rationale=(
                    f"Module {r['qname']} has fanin={r['fanin']} and {r['files_in_module']} "
                    "internal files (degree {degree}). Refactors here ripple widely; split "
                    "the module or stabilize the public API before touching it.".format(
                        degree=r["degree"]
                    )
                ),
                risk=risk,
                blast_radius=int(r["fanin"]),
            )
        )
    return items


async def find_duplicate_logic_stub(repo: str) -> list[RefactorItem]:
    """Placeholder until embeddings-based clustering is wired up.

    Currently returns nothing. The infrastructure (pgvector + node_embedding
    table) is in place; the clustering step needs an OPENAI_API_KEY during
    ingest to produce vectors first. M3 ships this as a stub on purpose so
    the agent contract is stable.
    """
    _ = repo
    return []


async def plan_refactors(repo: str) -> list[RefactorItem]:
    """Run every analysis and return a single ordered plan.

    Order: high-coupling first (architectural pain), then dead code (easy
    wins), then duplicates. Each section is sorted by blast_radius desc.
    """
    coupling = sorted(await find_high_coupling(repo), key=lambda i: -i.blast_radius)
    dead = await find_dead_code(repo)
    dupes = await find_duplicate_logic_stub(repo)
    return [*coupling, *dead, *dupes]


__all__ = [
    "Kind",
    "RefactorItem",
    "find_dead_code",
    "find_duplicate_logic_stub",
    "find_high_coupling",
    "plan_refactors",
]
