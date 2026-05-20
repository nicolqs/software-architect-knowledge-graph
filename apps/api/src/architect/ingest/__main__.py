"""CLI: `python -m architect.ingest <repo-path> [--name ...] [--reset] [--no-embeddings] [--confirm-cost] [--limit N]`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
import typer

from architect.config import Settings, get_settings
from architect.embeddings import store as embed_store
from architect.embeddings.client import BudgetExceededError
from architect.graph import client as graph_client
from architect.ingest.pipeline import IngestOptions, IngestStats, run_ingest

log = structlog.get_logger()
app = typer.Typer(add_completion=False, help="Ingest a repo into the graph.")


@app.command()
def main(
    repo_path: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    name: str | None = typer.Option(None, "--name", help="Repo name in the graph. Default: directory name."),
    reset: bool = typer.Option(False, "--reset", help="Drop existing nodes for this repo before ingest."),
    embed: bool = typer.Option(True, "--embed/--no-embeddings", help="Compute OpenAI embeddings (cached by content hash)."),
    confirm_cost: bool = typer.Option(False, "--confirm-cost", help="Override INGEST_COST_LIMIT_USD."),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of files (debugging)."),
) -> None:
    settings = get_settings()
    opts = IngestOptions(
        repo_path=repo_path,
        repo_name=name or repo_path.name,
        reset=reset,
        embed=embed,
        confirm_cost=confirm_cost,
        file_limit=limit,
    )
    typer.echo(f"Ingesting {opts.repo_path} as repo='{opts.repo_name}' (embed={opts.embed})...")
    try:
        stats = asyncio.run(_run(opts, settings))
    except BudgetExceededError as exc:
        typer.echo(f"[budget] {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"\nDone. Files parsed: {stats.files_parsed} | defs: {stats.definitions} | "
        f"calls: {stats.calls_resolved} | imports: {stats.imports_resolved} | "
        f"embed-api-calls: {stats.embeddings_api_calls} | "
        f"embed-cost-usd: ${stats.estimated_embed_cost_usd:.4f}"
    )


async def _run(opts: IngestOptions, settings: Settings) -> IngestStats:
    try:
        return await run_ingest(opts, settings)
    finally:
        await graph_client.close_driver()
        await embed_store.close_pool()


if __name__ == "__main__":
    app()
