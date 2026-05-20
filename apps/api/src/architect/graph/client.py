from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from architect.config import Settings

_driver: AsyncDriver | None = None


def init_driver(settings: Settings) -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized — call init_driver() at startup")
    return _driver


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a Neo4j session bound to the default database.

    All queries should be parameterized — never format Cypher strings.
    See docs/architecture.md for the agent tool-safety rationale.
    """
    driver = get_driver()
    async with driver.session() as s:
        yield s


async def ping() -> bool:
    async with session() as s:
        result = await s.run("RETURN 1 AS ok")
        record = await result.single()
        return bool(record and record["ok"] == 1)
