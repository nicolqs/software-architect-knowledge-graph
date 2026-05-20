"""Integration tests for the LLM cost meter + budget enforcer.

These tests need a live Postgres (the docker-compose `postgres` service).
They exercise the real `cost_log` table by inserting synthetic spend, then
asserting `check_budget()` raises only when the configured daily limit is
breached, and that the `_TokenMeterCallback` writes the row the meter
promises to write.

Skipped automatically when Postgres isn't reachable, so the test suite
still runs cleanly on a fresh checkout.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from langchain_core.outputs import LLMResult
from psycopg_pool import AsyncConnectionPool

from architect.agents.common.llm import (
    BudgetExceededError,
    LLMClient,
    _TokenMeterCallback,
)
from architect.config import Settings


def _live_postgres_available() -> bool:
    import socket

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _live_postgres_available(),
    reason="live Postgres not reachable; integration test skipped",
)


@pytest.fixture
async def pool():
    settings = Settings()
    p = AsyncConnectionPool(conninfo=settings.postgres_dsn, min_size=1, max_size=2, open=False)
    await p.open()
    yield p
    await p.close()


@pytest.fixture(autouse=True)
async def _clean_cost_log(pool: AsyncConnectionPool):
    # Tag rows we insert so we can clean them without touching real data.
    yield
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM cost_log WHERE component = 'test'")


async def test_budget_check_passes_when_under_limit(pool: AsyncConnectionPool) -> None:
    settings = Settings(daily_cost_limit_usd=10.0)
    client = LLMClient(settings, pool)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO cost_log (component, model, cost_usd) VALUES ('test', 'm', 1.00)",
        )
    # 1.00 < 10.00 — should not raise.
    await client.check_budget()


async def test_budget_check_raises_when_at_limit(pool: AsyncConnectionPool) -> None:
    settings = Settings(daily_cost_limit_usd=2.0)
    client = LLMClient(settings, pool)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO cost_log (component, model, cost_usd) VALUES ('test', 'm', 2.50)",
        )
    with pytest.raises(BudgetExceededError) as exc:
        await client.check_budget()
    assert "2.50" in str(exc.value) or "2.5" in str(exc.value)


async def test_metering_callback_writes_cost_log(pool: AsyncConnectionPool) -> None:
    cb = _TokenMeterCallback(pool, agent="test-agent")
    # 1k input + 500 output tokens for sonnet-4-6 at $3/$15 per M
    # → 1000/1e6 * 3 + 500/1e6 * 15 = 0.003 + 0.0075 = 0.0105 USD
    fake_result = LLMResult(
        generations=[],
        llm_output={
            "model_name": "claude-sonnet-4-6",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        },
    )
    await cb.on_llm_end(fake_result, run_id=uuid4())

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT component, agent, model, input_tokens, output_tokens, cost_usd::float8
            FROM cost_log
            WHERE component = 'agent' AND agent = 'test-agent' AND model = 'claude-sonnet-4-6'
            ORDER BY id DESC LIMIT 1
            """
        )
        row = await cur.fetchone()
    assert row is not None
    component, agent, model, in_tok, out_tok, cost = row
    assert component == "agent"
    assert agent == "test-agent"
    assert model == "claude-sonnet-4-6"
    assert in_tok == 1000
    assert out_tok == 500
    assert abs(cost - 0.0105) < 1e-9

    # Clean the row we wrote (component='agent', not 'test', so the autouse
    # fixture leaves it alone — clean explicitly).
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM cost_log WHERE component = 'agent' AND agent = 'test-agent'"
        )


async def test_unknown_model_falls_back_to_opus_pricing(pool: AsyncConnectionPool) -> None:
    cb = _TokenMeterCallback(pool, agent="test-fallback")
    # Same token counts, but unknown model name → should price at opus rate
    # 1000 * 15/1e6 + 500 * 75/1e6 = 0.015 + 0.0375 = 0.0525
    fake_result = LLMResult(
        generations=[],
        llm_output={
            "model_name": "totally-made-up",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        },
    )
    await cb.on_llm_end(fake_result, run_id=uuid4())
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT cost_usd::float8 FROM cost_log WHERE agent = 'test-fallback' ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
        await cur.execute("DELETE FROM cost_log WHERE agent = 'test-fallback'")
    assert row is not None
    assert abs(row[0] - 0.0525) < 1e-9
