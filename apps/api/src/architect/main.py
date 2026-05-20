from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from architect import __version__
from architect.agents.common.checkpointer import close_checkpointer, init_checkpointer
from architect.api.agents import router as echo_router
from architect.api.architect import router as architect_router
from architect.api.decisions import router as decisions_router
from architect.api.graph import router as graph_routes_router
from architect.api.refactor import router as refactor_router
from architect.api.reviewer import router as reviewer_router
from architect.api.sandbox import router as sandbox_router
from architect.api.tickets import router as tickets_router
from architect.config import get_settings
from architect.embeddings import store
from architect.graph import client as graph_client
from architect.graph import schema as graph_schema
from architect.migrations import run_migrations

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    graph_client.init_driver(settings)
    await store.init_pool(settings)
    pool = store.get_pool()
    async with pool.connection() as conn:
        applied = await run_migrations(conn)
    await graph_schema.apply()
    await init_checkpointer(settings)
    log.info(
        "startup",
        neo4j=settings.neo4j_uri,
        postgres=settings.postgres_host,
        sql_migrations_applied=applied,
    )
    try:
        yield
    finally:
        await close_checkpointer()
        await graph_client.close_driver()
        await store.close_pool()
        log.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Autonomous Software Architect",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(echo_router)
    app.include_router(architect_router)
    app.include_router(tickets_router)
    app.include_router(reviewer_router)
    app.include_router(refactor_router)
    app.include_router(graph_routes_router)
    app.include_router(decisions_router)
    app.include_router(sandbox_router)

    class Health(BaseModel):
        status: Literal["ok", "degraded"]
        version: str
        neo4j: bool
        postgres: bool

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        neo4j_ok = False
        postgres_ok = False
        try:
            neo4j_ok = await graph_client.ping()
        except Exception as exc:
            log.warning("neo4j_ping_failed", error=str(exc))
        try:
            postgres_ok = await store.ping()
        except Exception as exc:
            log.warning("postgres_ping_failed", error=str(exc))

        return Health(
            status="ok" if (neo4j_ok and postgres_ok) else "degraded",
            version=__version__,
            neo4j=neo4j_ok,
            postgres=postgres_ok,
        )

    return app


app = create_app()
