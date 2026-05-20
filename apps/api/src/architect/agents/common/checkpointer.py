"""LangGraph Postgres checkpointer wiring.

LangGraph's `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`
on its first call, which requires autocommit. Our app pool defaults to
transactional connections (right call for migrations + cost_log writes),
so we give the saver a dedicated connection with `autocommit=True`.

The saver instance is module-global because building one per call would
re-run schema checks; LangGraph's own docs recommend a single saver
shared across runs.
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection

from architect.config import Settings

log = structlog.get_logger()

_saver: AsyncPostgresSaver | None = None
_conn: AsyncConnection | None = None


async def init_checkpointer(settings: Settings) -> AsyncPostgresSaver:
    """Open a dedicated autocommit connection and initialize the saver. Idempotent."""
    global _saver, _conn
    if _saver is not None:
        return _saver
    _conn = await AsyncConnection.connect(settings.postgres_dsn, autocommit=True)
    _saver = AsyncPostgresSaver(_conn)  # type: ignore[arg-type]
    await _saver.setup()
    log.info("checkpointer_ready")
    return _saver


def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError(
            "Checkpointer not initialized — call init_checkpointer(settings) at startup"
        )
    return _saver


async def close_checkpointer() -> None:
    global _saver, _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
    _saver = None


def reset_for_tests() -> None:
    """Reset the module-global so tests can re-init with fresh state."""
    global _saver, _conn
    _saver = None
    _conn = None
