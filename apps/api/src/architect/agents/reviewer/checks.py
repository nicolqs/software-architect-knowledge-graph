"""Graph-rules-based checks for the PR Reviewer agent.

v1 keeps this LLM-free: every check is a Cypher query against the
already-ingested graph. The reviewer doesn't need an LLM to flag
circular imports or untested high-fanin code — these are deterministic
properties of the graph.

LLM-based checks (e.g. "does this change violate the architecture doc?")
land in M3 when there's a real arch doc to compare against. For v1 the
LLM is opt-in: the agent calls the LLM only to summarize findings.

Inputs:
- `repo`: which ingested repo to analyze.
- `changed_files`: list of file paths (relative, posix) the PR touches.

Outputs: list of `Finding` records sorted by severity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import structlog

from architect.graph import client as graph_client

log = structlog.get_logger()

Severity = Literal["critical", "important", "advisory"]


@dataclass(slots=True)
class Finding:
    severity: Severity
    rule: str
    message: str
    qname: str | None = None
    file_path: str | None = None
    line: int | None = None


async def _changed_functions(repo: str, paths: list[str]) -> list[dict[str, Any]]:
    """Functions defined in any of the changed files."""
    if not paths:
        return []
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:CONTAINS]->(fn:Function)
            WHERE file.path IN $paths
            RETURN fn.qname AS qname, fn.name AS name,
                   file.path AS file_path, fn.line AS line
            """,
            repo=repo,
            paths=paths,
        )
        return list(await result.data())


async def _circular_imports(repo: str, paths: list[str]) -> list[tuple[str, str]]:
    """Find import cycles touching any of the changed files.

    APOC's pathExpand variants over IMPORTS would work, but for v1 we use a
    simple 2-hop cycle detection: file A imports module B which is imported
    by file A's own module. Good enough as a smoke detector.
    """
    if not paths:
        return []
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (a:File {repo: $repo})-[:IMPORTS]->(m1:Module)<-[:IN_MODULE]-(b:File),
                  (b)-[:IMPORTS]->(m2:Module)<-[:IN_MODULE]-(a)
            WHERE a.path IN $paths AND a.path < b.path
            RETURN DISTINCT a.path AS a, b.path AS b
            LIMIT 50
            """,
            repo=repo,
            paths=paths,
        )
        return [(r["a"], r["b"]) for r in await result.data()]


async def _high_fanin_changes(
    repo: str, paths: list[str], threshold: int = 10
) -> list[dict[str, Any]]:
    """Touched functions that are called from many places."""
    if not paths:
        return []
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:CONTAINS]->(fn:Function)
            WHERE file.path IN $paths
            WITH fn, file, count{(c:Function)-[:CALLS]->(fn)} AS fanin
            WHERE fanin >= $threshold
            RETURN fn.qname AS qname, fn.name AS name,
                   file.path AS file_path, fn.line AS line, fanin
            ORDER BY fanin DESC
            LIMIT 20
            """,
            repo=repo,
            paths=paths,
            threshold=threshold,
        )
        return list(await result.data())


async def _missing_tests(repo: str, paths: list[str]) -> list[dict[str, Any]]:
    """Touched non-test functions where no test-named function calls them.

    Heuristic: a test exists for `foo` if any caller's file path contains
    'test' AND the caller's name starts with 'test'. Not perfect but
    surfaces obvious gaps; the LLM summary step refines the message.
    """
    if not paths:
        return []
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:CONTAINS]->(fn:Function)
            WHERE file.path IN $paths
              AND NOT file.path CONTAINS 'test'
              AND NOT fn.name STARTS WITH '_'
            OPTIONAL MATCH (test_fn:Function {repo: $repo})-[:CALLS]->(fn)
            WHERE test_fn.name STARTS WITH 'test'
            WITH fn, file, count(test_fn) AS test_count
            WHERE test_count = 0
            RETURN fn.qname AS qname, fn.name AS name,
                   file.path AS file_path, fn.line AS line
            LIMIT 50
            """,
            repo=repo,
            paths=paths,
        )
        return list(await result.data())


async def _low_confidence_callers(repo: str, paths: list[str]) -> list[dict[str, Any]]:
    """Edges into changed functions where confidence dropped below 0.5.

    These are "we *think* this calls you, but we can't prove it" — risky
    surface area for a refactor.
    """
    if not paths:
        return []
    async with graph_client.session() as s:
        result = await s.run(
            """
            MATCH (file:File {repo: $repo})-[:CONTAINS]->(fn:Function),
                  (caller:Function {repo: $repo})-[r:CALLS]->(fn)
            WHERE file.path IN $paths AND r.confidence < 0.5
            RETURN fn.qname AS qname, caller.qname AS caller, r.confidence AS confidence
            LIMIT 50
            """,
            repo=repo,
            paths=paths,
        )
        return list(await result.data())


async def run_checks(repo: str, changed_files: list[str]) -> list[Finding]:
    findings: list[Finding] = []

    # circular imports → critical
    for a, b in await _circular_imports(repo, changed_files):
        findings.append(
            Finding(
                severity="critical",
                rule="circular_import",
                message=f"Circular import detected: {a} ↔ {b}",
                file_path=a,
            )
        )

    # high fan-in changes → important
    for row in await _high_fanin_changes(repo, changed_files):
        findings.append(
            Finding(
                severity="important",
                rule="high_fanin_change",
                message=(
                    f"{row['name']} has {row['fanin']} callers — a change here "
                    "has wide blast radius. Confirm regression tests cover the call sites."
                ),
                qname=row["qname"],
                file_path=row["file_path"],
                line=row["line"],
            )
        )

    # low-confidence callers → important
    seen_low_conf: set[str] = set()
    for row in await _low_confidence_callers(repo, changed_files):
        key = row["qname"]
        if key in seen_low_conf:
            continue
        seen_low_conf.add(key)
        findings.append(
            Finding(
                severity="important",
                rule="low_confidence_callers",
                message=(
                    f"{key} has callers whose call edge confidence is below 0.5 "
                    "(dynamic dispatch or unresolved imports). Manual review recommended."
                ),
                qname=key,
            )
        )

    # missing tests → advisory
    for row in await _missing_tests(repo, changed_files):
        findings.append(
            Finding(
                severity="advisory",
                rule="missing_tests",
                message=f"No test function appears to call {row['name']}. Consider adding coverage.",
                qname=row["qname"],
                file_path=row["file_path"],
                line=row["line"],
            )
        )

    # Sort by severity, then by file/line for predictable output
    severity_rank = {"critical": 0, "important": 1, "advisory": 2}
    findings.sort(key=lambda f: (severity_rank[f.severity], f.file_path or "", f.line or 0))
    return findings


__all__ = ["Finding", "Severity", "run_checks"]
