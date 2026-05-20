from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from architect import __version__
from architect.config import get_settings
from architect.embeddings import store
from architect.graph import client as graph_client

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    graph_client.init_driver(settings)
    await store.init_pool(settings)
    log.info("startup", neo4j=settings.neo4j_uri, postgres=settings.postgres_host)
    try:
        yield
    finally:
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
