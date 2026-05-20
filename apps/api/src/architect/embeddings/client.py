"""OpenAI embeddings with content-hash cache + cost preflight.

Design:
- Hash the input text. Check `embedding_cache`; if hit, reuse the vector.
- Anything missing is batched into OpenAI calls (max 96 inputs / 8191 tokens each).
- Vectors get written to `embedding_cache` and pointed at by `node_embedding`.
- Cost is metered in `cost_log` and enforced by `BudgetExceededError` raised from
  `estimate_cost()` if the planned ingest is over the configured ceiling.

Gracefully degrades when `OPENAI_API_KEY` is empty: returns a NoopEmbeddingClient
that logs once and writes nothing. Lets us iterate on the parser without burning
API credit.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import structlog
import tiktoken
from openai import AsyncOpenAI
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from architect.config import Settings

log = structlog.get_logger()

# text-embedding-3-large pricing as of 2025: $0.13 per 1M input tokens.
# Recorded here so the preflight is deterministic regardless of OpenAI dashboards.
_PRICE_PER_MILLION_TOKENS_USD = 0.13
_EMBEDDING_DIMENSIONS = 1536  # truncated; matches the pgvector schema.
_MAX_INPUTS_PER_BATCH = 96
_MAX_TOKENS_PER_INPUT = 8191


class BudgetExceededError(RuntimeError):
    """Raised when a planned operation would exceed a configured cost ceiling."""


@dataclass(slots=True)
class EmbedItem:
    repo: str
    node_qname: str
    node_label: str  # 'Function' | 'Class' | 'File'
    content: str


@dataclass(slots=True)
class EstimatedCost:
    total_tokens: int
    cost_usd: float
    cached_items: int
    uncached_items: int


class EmbeddingClient(Protocol):
    async def estimate_cost(self, items: Sequence[EmbedItem]) -> EstimatedCost: ...
    async def embed_many(self, items: Sequence[EmbedItem]) -> int: ...


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class NoopEmbeddingClient:
    """Used when no OpenAI key is configured. Logs once, then silently skips."""

    def __init__(self) -> None:
        self._warned = False

    async def estimate_cost(self, items: Sequence[EmbedItem]) -> EstimatedCost:
        return EstimatedCost(total_tokens=0, cost_usd=0.0, cached_items=0, uncached_items=0)

    async def embed_many(self, items: Sequence[EmbedItem]) -> int:
        if not self._warned and items:
            log.warning("embeddings_disabled", reason="OPENAI_API_KEY missing — skipping all embeds")
            self._warned = True
        return 0


class OpenAIEmbeddingClient:
    def __init__(self, settings: Settings, pool: AsyncConnectionPool) -> None:
        self._settings = settings
        self._pool = pool
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._encoder = tiktoken.get_encoding("cl100k_base")
        self._model = settings.embedding_model

    def _count_tokens(self, text: str) -> int:
        # cl100k_base is the encoder used by the embedding-3 family.
        return len(self._encoder.encode(text))

    async def estimate_cost(self, items: Sequence[EmbedItem]) -> EstimatedCost:
        hashes = [content_hash(it.content) for it in items]
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT content_hash FROM embedding_cache WHERE content_hash = ANY(%s)",
                (hashes,),
            )
            cached = {row[0] for row in await cur.fetchall()}
        total_tokens = 0
        uncached = 0
        for it, h in zip(items, hashes, strict=True):
            if h in cached:
                continue
            uncached += 1
            total_tokens += min(self._count_tokens(it.content), _MAX_TOKENS_PER_INPUT)
        cost = total_tokens / 1_000_000 * _PRICE_PER_MILLION_TOKENS_USD
        return EstimatedCost(
            total_tokens=total_tokens,
            cost_usd=cost,
            cached_items=len(items) - uncached,
            uncached_items=uncached,
        )

    async def embed_many(self, items: Sequence[EmbedItem]) -> int:
        """Embed everything, using the cache where possible. Returns API calls made."""
        async with self._pool.connection() as conn:
            await register_vector_async(conn)
            api_calls = 0
            uncached_items: list[EmbedItem] = []
            uncached_hashes: list[str] = []
            cached_hashes_by_item: dict[str, str] = {}

            hashes = [content_hash(it.content) for it in items]
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content_hash FROM embedding_cache WHERE content_hash = ANY(%s)",
                    (hashes,),
                )
                cached = {row[0] for row in await cur.fetchall()}

            for it, h in zip(items, hashes, strict=True):
                if h in cached:
                    cached_hashes_by_item[it.node_qname] = h
                else:
                    uncached_items.append(it)
                    uncached_hashes.append(h)

            # Embed uncached in batches.
            for batch_start in range(0, len(uncached_items), _MAX_INPUTS_PER_BATCH):
                batch = uncached_items[batch_start : batch_start + _MAX_INPUTS_PER_BATCH]
                batch_hashes = uncached_hashes[batch_start : batch_start + _MAX_INPUTS_PER_BATCH]
                texts = [self._truncate(it.content) for it in batch]
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                    dimensions=_EMBEDDING_DIMENSIONS,
                )
                api_calls += 1
                total_tokens = response.usage.total_tokens
                cost = total_tokens / 1_000_000 * _PRICE_PER_MILLION_TOKENS_USD
                async with conn.cursor() as cur:
                    await cur.executemany(
                        """
                        INSERT INTO embedding_cache (content_hash, model, dimensions, embedding)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (content_hash) DO NOTHING
                        """,
                        [
                            (h, self._model, _EMBEDDING_DIMENSIONS, d.embedding)
                            for h, d in zip(batch_hashes, response.data, strict=True)
                        ],
                    )
                    await cur.execute(
                        """
                        INSERT INTO cost_log (component, model, input_tokens, cost_usd)
                        VALUES (%s, %s, %s, %s)
                        """,
                        ("embedding", self._model, total_tokens, cost),
                    )
                for it, h in zip(batch, batch_hashes, strict=True):
                    cached_hashes_by_item[it.node_qname] = h

            # Point every node at its (now-cached) embedding.
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO node_embedding (node_qname, node_label, repo, content_hash)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (node_qname) DO UPDATE
                        SET content_hash = EXCLUDED.content_hash,
                            updated_at = now()
                    """,
                    [
                        (it.node_qname, it.node_label, it.repo, cached_hashes_by_item[it.node_qname])
                        for it in items
                        if it.node_qname in cached_hashes_by_item
                    ],
                )
            return api_calls

    def _truncate(self, text: str) -> str:
        """Truncate at the encoder level so we don't blow `_MAX_TOKENS_PER_INPUT`."""
        tokens = self._encoder.encode(text)
        if len(tokens) <= _MAX_TOKENS_PER_INPUT:
            return text
        return self._encoder.decode(tokens[:_MAX_TOKENS_PER_INPUT])


def make_client(settings: Settings, pool: AsyncConnectionPool) -> EmbeddingClient:
    if not settings.openai_api_key:
        return NoopEmbeddingClient()
    return OpenAIEmbeddingClient(settings, pool)


def enforce_budget(estimate: EstimatedCost, limit_usd: float, confirmed: bool) -> None:
    if estimate.cost_usd > limit_usd and not confirmed:
        raise BudgetExceededError(
            f"Estimated embedding cost ${estimate.cost_usd:.4f} exceeds "
            f"INGEST_COST_LIMIT_USD=${limit_usd:.2f}. "
            f"Re-run with --confirm-cost to override."
        )


__all__ = [
    "BudgetExceededError",
    "EmbedItem",
    "EmbeddingClient",
    "EstimatedCost",
    "NoopEmbeddingClient",
    "OpenAIEmbeddingClient",
    "content_hash",
    "enforce_budget",
    "make_client",
]
