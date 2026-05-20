"""LLM client wrapper: model factory + token meter + budget enforcement.

Why this exists:
- Every Anthropic call is metered into `cost_log` so we can see per-agent
  spend and enforce a daily ceiling.
- Budget enforcement is *before* the call (raises `BudgetExceededError`),
  not best-effort post-hoc. The plan calls this out as non-negotiable.
- Model routing (Sonnet default, Opus for Architect synthesis) is a thin
  config layer; agents stay model-agnostic.

Not subclassing `ChatAnthropic` because Pydantic-modeled LangChain
classes resist clean subclassing. Instead we attach a callback for
metering and expose an explicit `check_budget()` for pre-call gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from architect.config import Settings

log = structlog.get_logger()


class BudgetExceededError(RuntimeError):
    """Raised when the daily LLM spend would exceed `DAILY_COST_LIMIT_USD`."""


# USD per 1M tokens, baked in for v1. We pin these so the meter is
# deterministic regardless of pricing-page changes; revisit when models bump.
_PRICING: dict[str, tuple[float, float]] = {
    # model_name → (input_per_million, output_per_million)
    # Anthropic
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (15.0, 75.0),
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.0, 30.0),
}


def _price_for(model_name: str) -> tuple[float, float]:
    if model_name in _PRICING:
        return _PRICING[model_name]
    # Fall back to the most-expensive known model so unknown names surface
    # as expensive rather than silently free.
    return _PRICING["claude-opus-4-7"]


@dataclass(slots=True)
class CostRecord:
    component: str
    agent: str | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class _TokenMeterCallback(AsyncCallbackHandler):
    """Writes one cost_log row per LLM completion.

    Token counts come from the `LLMResult.llm_output['usage']` map that
    langchain-anthropic populates for every Anthropic call.
    """

    def __init__(self, pool: AsyncConnectionPool, agent: str | None) -> None:
        self._pool = pool
        self._agent = agent

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        # Anthropic and OpenAI report usage under different keys.
        # langchain-anthropic: llm_output['usage'] = {input_tokens, output_tokens}
        # langchain-openai:    llm_output['token_usage'] = {prompt_tokens, completion_tokens, total_tokens}
        llm_output = response.llm_output or {}
        usage = llm_output.get("usage") or llm_output.get("token_usage") or {}
        model = (
            llm_output.get("model_name")
            or llm_output.get("model")
            or "unknown"
        )
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        in_price, out_price = _price_for(model)
        cost = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO cost_log (component, agent, model, input_tokens, output_tokens, cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                ("agent", self._agent, model, input_tokens, output_tokens, cost),
            )
        log.debug(
            "llm_metered",
            agent=self._agent,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )


class LLMClient:
    """Build LangChain chat models with budget + metering attached.

    Typical usage inside an agent node:
        await client.check_budget()
        model = client.make_model(agent="echo")
        response = await model.ainvoke(messages)

    The check is explicit (one line) rather than implicit-in-`make_model`
    so agents can decide whether to retry, downgrade the model, or surface
    the budget error to the caller.
    """

    def __init__(self, settings: Settings, pool: AsyncConnectionPool) -> None:
        self._settings = settings
        self._pool = pool

    def make_model(
        self,
        *,
        agent: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.2,
    ) -> BaseChatModel:
        """Build a metered chat model for the configured provider.

        Falls back to the provider's default model name unless `model_name` is
        supplied. Architects pass `settings.active_architect_model` here so the
        synthesize step gets Opus (Anthropic) or gpt-4o (OpenAI).
        """
        provider = self._settings.agent_provider
        name = model_name or self._settings.active_default_model
        callbacks: list[BaseCallbackHandler] = [_TokenMeterCallback(self._pool, agent)]
        if provider == "openai":
            return ChatOpenAI(
                model=name,
                api_key=SecretStr(self._settings.openai_api_key),
                temperature=temperature,
                callbacks=callbacks,
            )
        return ChatAnthropic(
            model_name=name,
            api_key=SecretStr(self._settings.anthropic_api_key),
            temperature=temperature,
            callbacks=callbacks,
            timeout=None,
            stop=None,
        )

    async def check_budget(self) -> None:
        """Raise BudgetExceededError if today's spend is already at the ceiling.

        Reads cost_log for the current calendar day. Cheap query; safe to call
        on every agent turn.
        """
        limit = self._settings.daily_cost_limit_usd
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0)::float8
                FROM cost_log
                WHERE occurred_at >= date_trunc('day', now())
                """
            )
            row = await cur.fetchone()
            spent = float(row[0]) if row else 0.0
        if spent >= limit:
            raise BudgetExceededError(
                f"Daily LLM spend ${spent:.2f} already at/above "
                f"DAILY_COST_LIMIT_USD=${limit:.2f}. Refusing further LLM calls until tomorrow."
            )
        log.debug("budget_ok", spent_usd=round(spent, 4), limit_usd=limit)

__all__ = ["BudgetExceededError", "CostRecord", "LLMClient"]
