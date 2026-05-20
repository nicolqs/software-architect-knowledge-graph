"""Graph writer: batched Cypher upserts for parsed files + resolved edges.

All queries are parameterized — agents and writers go through the same
discipline (see docs/architecture.md). The writer is the only place we
explicitly mutate graph nodes; agents stage proposals via the typed
toolkit landing in M2.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import structlog

from architect.graph import client as graph_client
from architect.ingest.resolver import ResolvedRepo
from architect.ingest.types import ParsedFile

log = structlog.get_logger()

_BATCH_SIZE = 200


async def upsert_repo(repo: str, root_path: str) -> None:
    async with graph_client.session() as s:
        await s.run(
            """
            MERGE (r:Repo {name: $name})
            SET r.path = $path, r.ingested_at = timestamp()
            """,
            name=repo,
            path=root_path,
        )


async def write_files(repo: str, files: Iterable[ParsedFile]) -> int:
    """Create File + Module nodes and HAS_FILE / IN_MODULE / CONTAINS edges.

    Done in three passes per batch (file shells, then Function defs, then Class defs)
    so each Cypher statement stays simple and any per-pass failure is easy to
    interpret. Performance is fine — batches are ~200 files.
    """
    files_list = list(files)
    total = 0
    for batch in _batched(files_list, _BATCH_SIZE):
        file_rows = [
            {
                "path": pf.path,
                "language": pf.language,
                "content_hash": pf.content_hash,
                "loc": pf.loc,
                "module_qname": pf.module_qname,
            }
            for pf in batch
        ]
        function_rows = [
            {
                "file_path": pf.path,
                "qname": d.qname,
                "name": d.name,
                "line": d.line,
                "end_line": d.end_line,
                "is_async": d.is_async,
                "signature": d.signature,
            }
            for pf in batch
            for d in pf.definitions
            if d.kind == "function"
        ]
        class_rows = [
            {
                "file_path": pf.path,
                "qname": d.qname,
                "name": d.name,
                "line": d.line,
                "end_line": d.end_line,
            }
            for pf in batch
            for d in pf.definitions
            if d.kind == "class"
        ]
        async with graph_client.session() as s:
            await s.run(
                """
                MATCH (r:Repo {name: $repo})
                UNWIND $rows AS f
                MERGE (file:File {repo: $repo, path: f.path})
                SET file.language = f.language,
                    file.content_hash = f.content_hash,
                    file.loc = f.loc
                MERGE (r)-[:HAS_FILE]->(file)
                MERGE (mod:Module {repo: $repo, qname: f.module_qname})
                MERGE (file)-[:IN_MODULE]->(mod)
                """,
                repo=repo,
                rows=file_rows,
            )
            if function_rows:
                await s.run(
                    """
                    UNWIND $rows AS d
                    MATCH (file:File {repo: $repo, path: d.file_path})
                    MERGE (fn:Function {repo: $repo, qname: d.qname})
                    SET fn.name = d.name,
                        fn.line = d.line,
                        fn.end_line = d.end_line,
                        fn.is_async = d.is_async,
                        fn.signature = d.signature,
                        fn.file_path = d.file_path
                    MERGE (file)-[:CONTAINS]->(fn)
                    """,
                    repo=repo,
                    rows=function_rows,
                )
            if class_rows:
                await s.run(
                    """
                    UNWIND $rows AS d
                    MATCH (file:File {repo: $repo, path: d.file_path})
                    MERGE (c:Class {repo: $repo, qname: d.qname})
                    SET c.name = d.name,
                        c.line = d.line,
                        c.end_line = d.end_line,
                        c.file_path = d.file_path
                    MERGE (file)-[:CONTAINS]->(c)
                    """,
                    repo=repo,
                    rows=class_rows,
                )
        total += len(batch)
    return total


async def link_methods_to_classes(repo: str, files: Iterable[ParsedFile]) -> int:
    """For every Function with a `parent_qname`, link the parent Class -> Function."""
    pairs: list[dict[str, str]] = []
    for pf in files:
        for d in pf.definitions:
            if d.kind == "function" and d.parent_qname is not None:
                pairs.append({"parent": d.parent_qname, "child": d.qname})
    if not pairs:
        return 0
    async with graph_client.session() as s:
        await s.run(
            """
            UNWIND $pairs AS p
            MATCH (parent:Class {repo: $repo, qname: p.parent})
            MATCH (child:Function {repo: $repo, qname: p.child})
            MERGE (parent)-[:CONTAINS]->(child)
            """,
            repo=repo,
            pairs=pairs,
        )
    return len(pairs)


async def write_edges(repo: str, resolved: ResolvedRepo) -> tuple[int, int]:
    """Create CALLS and IMPORTS edges. Returns (calls_written, imports_written)."""
    call_params = [
        {
            "caller": c.caller_qname,
            "target": c.target_qname,
            "confidence": c.confidence,
            "line": c.line,
        }
        for c in resolved.calls
    ]
    import_params = [
        {
            "file_path": i.file_path,
            "target": i.target_qname,
            "confidence": i.confidence,
            "line": i.line,
        }
        for i in resolved.imports
    ]

    calls_written = 0
    for batch in _batched(call_params, _BATCH_SIZE):
        async with graph_client.session() as s:
            await s.run(
                """
                UNWIND $rows AS r
                MATCH (caller:Function {repo: $repo, qname: r.caller})
                MERGE (target:Function {repo: $repo, qname: r.target})
                MERGE (caller)-[c:CALLS]->(target)
                SET c.confidence = r.confidence,
                    c.last_line = r.line,
                    c.count = coalesce(c.count, 0) + 1
                """,
                repo=repo,
                rows=batch,
            )
        calls_written += len(batch)

    imports_written = 0
    for batch in _batched(import_params, _BATCH_SIZE):
        async with graph_client.session() as s:
            await s.run(
                """
                UNWIND $rows AS r
                MATCH (file:File {repo: $repo, path: r.file_path})
                MERGE (target:Module {repo: $repo, qname: r.target})
                MERGE (file)-[i:IMPORTS]->(target)
                SET i.confidence = r.confidence, i.line = r.line
                """,
                repo=repo,
                rows=batch,
            )
        imports_written += len(batch)
    return calls_written, imports_written


def _batched(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
