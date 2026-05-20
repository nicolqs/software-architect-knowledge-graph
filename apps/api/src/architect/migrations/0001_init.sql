-- Core tables for ingestion and cost tracking.
-- pgvector extension is created by docker-entrypoint init.sql; safe to re-assert.
CREATE EXTENSION IF NOT EXISTS vector;

-- Embedding cache: content_hash → vector. Lets re-ingest skip unchanged AST nodes.
-- text-embedding-3-large is 3072-dim by default; we pin to 1536 (truncated) to
-- keep pgvector indexes feasible and cost lower. The model supports `dimensions`
-- request param to truncate at the API level.
CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash    TEXT        PRIMARY KEY,
    model           TEXT        NOT NULL,
    dimensions      INT         NOT NULL,
    embedding       vector(1536) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Embeddings keyed by graph node id (the Neo4j element id, or our own qname).
-- Distinguished from the cache: cache is keyed by content; this is keyed by graph node.
-- One graph node can move between content hashes over time; the cache row outlives it.
CREATE TABLE IF NOT EXISTS node_embedding (
    node_qname      TEXT        PRIMARY KEY,
    node_label      TEXT        NOT NULL,
    repo            TEXT        NOT NULL,
    content_hash    TEXT        NOT NULL REFERENCES embedding_cache(content_hash),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS node_embedding_repo_idx       ON node_embedding (repo);
CREATE INDEX IF NOT EXISTS node_embedding_label_idx      ON node_embedding (node_label);

-- ANN index over the cache vectors. ivfflat needs ANALYZE'd data to be useful;
-- we create it now and let usage warm it. cosine because embedding-3-large
-- behaves well under cosine.
CREATE INDEX IF NOT EXISTS embedding_cache_ann_idx
    ON embedding_cache USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Cost log: every LLM/embedding call is metered here. Read by the budget enforcer.
CREATE TABLE IF NOT EXISTS cost_log (
    id              BIGSERIAL   PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    component       TEXT        NOT NULL,        -- 'embedding' | 'agent' | etc.
    agent           TEXT        NULL,            -- 'architect' | 'reviewer' | ...
    model           TEXT        NOT NULL,
    input_tokens    INT         NOT NULL DEFAULT 0,
    output_tokens   INT         NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6) NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS cost_log_occurred_idx ON cost_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS cost_log_component_idx ON cost_log (component);
