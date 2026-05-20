from psycopg_pool import AsyncConnectionPool

from architect.config import Settings

_pool: AsyncConnectionPool | None = None


async def init_pool(settings: Settings) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=settings.postgres_dsn,
            min_size=1,
            max_size=10,
            open=False,
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized — call init_pool() at startup")
    return _pool


async def ping() -> bool:
    async with get_pool().connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
        row = await cur.fetchone()
        return bool(row and row[0] == 1)
