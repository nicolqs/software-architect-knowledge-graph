"""Lightweight, idempotent SQL migration runner.

Each `.sql` file in this directory is applied in lexical order. Applied
migrations are tracked in `schema_version`. Naming: `NNNN_short_name.sql`.

Why not Alembic: we don't need ORM-aware autogen yet, and Alembic adds a
lot of ceremony for a project where schema changes are infrequent and we
prefer raw, reviewable Cypher / SQL.
"""

from __future__ import annotations

import importlib.resources
import re
from collections.abc import Iterable

import structlog
from psycopg import AsyncConnection

log = structlog.get_logger()

_MIGRATION_PATTERN = re.compile(r"^\d{4}_[\w-]+\.sql$")


def _migration_files() -> list[str]:
    files = importlib.resources.files(__name__)
    names = [
        f.name
        for f in files.iterdir()
        if f.is_file() and _MIGRATION_PATTERN.match(f.name)
    ]
    return sorted(names)


def _read_migration(name: str) -> str:
    return importlib.resources.files(__name__).joinpath(name).read_text(encoding="utf-8")


async def _applied_versions(conn: AsyncConnection) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await cur.execute("SELECT name FROM schema_version")
        rows = await cur.fetchall()
        return {row[0] for row in rows}


async def run_migrations(conn: AsyncConnection, *, only: Iterable[str] | None = None) -> list[str]:
    """Apply pending migrations. Returns names actually applied this call.

    Each migration runs in its own transaction.
    """
    applied = await _applied_versions(conn)
    candidates = list(only) if only is not None else _migration_files()
    newly_applied: list[str] = []
    for name in candidates:
        if name in applied:
            continue
        sql = _read_migration(name)
        async with conn.transaction(), conn.cursor() as cur:
            await cur.execute(sql)
            await cur.execute(
                "INSERT INTO schema_version (name) VALUES (%s)",
                (name,),
            )
        log.info("migration_applied", name=name)
        newly_applied.append(name)
    return newly_applied
