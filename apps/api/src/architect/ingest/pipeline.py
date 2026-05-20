"""Top-level ingest orchestrator.

Wires the walker, parser, resolver, graph writer, and embedding client.
Called by the CLI in `architect/ingest/__main__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from tqdm.asyncio import tqdm

from architect.config import Settings
from architect.embeddings import client as embed_client
from architect.embeddings import store as embed_store
from architect.embeddings.client import EmbedItem
from architect.graph import client as graph_client
from architect.graph import schema as graph_schema
from architect.ingest import resolver as resolver_mod
from architect.ingest import writer
from architect.ingest.parsers import parse_file
from architect.ingest.types import ParsedFile
from architect.ingest.walker import walk_repo
from architect.migrations import run_migrations

log = structlog.get_logger()


@dataclass(slots=True)
class IngestOptions:
    repo_path: Path
    repo_name: str
    reset: bool = False
    embed: bool = True
    confirm_cost: bool = False
    file_limit: int | None = None


@dataclass(slots=True)
class IngestStats:
    files_parsed: int
    definitions: int
    calls_resolved: int
    imports_resolved: int
    files_written: int
    embeddings_api_calls: int
    estimated_embed_cost_usd: float


async def run_ingest(opts: IngestOptions, settings: Settings) -> IngestStats:
    """Run the full ingest pipeline. Caller is responsible for init/close."""
    # Bring driver + pool up.
    graph_client.init_driver(settings)
    await embed_store.init_pool(settings)
    pool = embed_store.get_pool()
    async with pool.connection() as conn:
        await run_migrations(conn)
    await graph_schema.apply()

    if opts.reset:
        log.info("ingest_reset", repo=opts.repo_name)
        await graph_schema.drop_repo(opts.repo_name)

    await writer.upsert_repo(opts.repo_name, str(opts.repo_path))

    # Pass 1: parse every file into memory. For ~10k files this is fine —
    # ParsedFile is small. If we outgrow it we'll switch to streaming.
    parsed: list[ParsedFile] = []
    for rel_path, data in walk_repo(opts.repo_path, limit=opts.file_limit):
        try:
            pf = parse_file(repo=opts.repo_name, rel_path=rel_path, source=data)
        except Exception as exc:
            log.warning("parse_failed", path=rel_path, error=str(exc))
            continue
        if pf is not None:
            parsed.append(pf)

    log.info("ingest_parsed", count=len(parsed))

    # Pass 2: resolve cross-file calls and imports.
    resolved = resolver_mod.resolve(parsed)
    log.info(
        "ingest_resolved",
        calls=len(resolved.calls),
        imports=len(resolved.imports),
    )

    # Pass 3: write to Neo4j.
    files_written = await writer.write_files(opts.repo_name, parsed)
    await writer.link_methods_to_classes(opts.repo_name, parsed)
    calls_w, imports_w = await writer.write_edges(opts.repo_name, resolved)
    log.info(
        "ingest_written",
        files=files_written,
        calls=calls_w,
        imports=imports_w,
    )

    # Pass 4: embeddings — one item per function/class/file.
    api_calls = 0
    estimated_cost = 0.0
    if opts.embed:
        client = embed_client.make_client(settings, pool)
        items = _build_embed_items(parsed)
        estimate = await client.estimate_cost(items)
        estimated_cost = estimate.cost_usd
        log.info(
            "embedding_preflight",
            uncached=estimate.uncached_items,
            cached=estimate.cached_items,
            tokens=estimate.total_tokens,
            cost_usd=round(estimate.cost_usd, 4),
        )
        embed_client.enforce_budget(estimate, settings.ingest_cost_limit_usd, opts.confirm_cost)
        api_calls = await _embed_with_progress(client, items)

    return IngestStats(
        files_parsed=len(parsed),
        definitions=sum(len(p.definitions) for p in parsed),
        calls_resolved=len(resolved.calls),
        imports_resolved=len(resolved.imports),
        files_written=files_written,
        embeddings_api_calls=api_calls,
        estimated_embed_cost_usd=estimated_cost,
    )


def _build_embed_items(parsed: list[ParsedFile]) -> list[EmbedItem]:
    """One embed item per Function / Class. File-level embeds wait until we
    keep raw source in ParsedFile — embedding just the path is not useful.
    """
    items: list[EmbedItem] = []
    for pf in parsed:
        for d in pf.definitions:
            if not d.body_text:
                continue
            items.append(
                EmbedItem(
                    repo=pf.repo,
                    node_qname=d.qname,
                    node_label="Function" if d.kind == "function" else "Class",
                    content=f"{d.signature}\n\n{d.body_text}",
                )
            )
    return items


async def _embed_with_progress(client: embed_client.EmbeddingClient, items: list[EmbedItem]) -> int:
    # tqdm wraps a coroutine; for batched embed_many we just call it once.
    bar = tqdm(total=len(items), desc="embedding", unit="node")
    bar.update(0)
    try:
        api_calls = await client.embed_many(items)
        bar.update(len(items))
        return api_calls
    finally:
        bar.close()
