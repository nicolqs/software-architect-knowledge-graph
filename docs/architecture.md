# Architecture

The v1 system as built. See `~/.claude/plans/can-you-create-a-luminous-shell.md` for the original plan and the load-bearing design decisions; this doc is the post-build snapshot.

## High-level shape

```
┌─────────────────────────────────────────────────────────────────────┐
│  Vite + React + TS UI (graph viewer, agent tabs, decisions)         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP (CORS-allowed)
┌───────────────────────────────▼─────────────────────────────────────┐
│  FastAPI gateway                                                     │
│    /health  /graph/*  /agents/*  /decisions/*  /sandbox/*            │
└────┬──────────┬───────────┬────────────────────────┬────────────────┘
     │          │           │                        │
┌────▼─────┐ ┌──▼────────┐ ┌▼────────────────────┐ ┌─▼──────────────┐
│ LangGraph│ │ Ingestion │ │ Decision log applier │ │ Docker sandbox │
│ agents   │ │ pipeline  │ │ (apply_proposal)     │ │ (rootless,     │
│  echo    │ │ tree-     │ │                      │ │  network off)  │
│  archct  │ │ sitter →  │ │                      │ │                │
│  tickets │ │ Neo4j +   │ │                      │ │                │
│  review  │ │ pgvector  │ │                      │ │                │
│  refac   │ │           │ │                      │ │                │
└──┬────┬──┘ └─────┬─────┘ └──────────────────────┘ └────────────────┘
   │    │         │
   │    │ typed   │
   │    │ tools   │
   │    │         │
┌──▼────▼─────────▼────────────────────┐
│ Shared infra                          │
│  Neo4j 5 (+APOC) — knowledge graph    │
│  Postgres 16 + pgvector — embeddings, │
│    cost_log, decision_log,            │
│    LangGraph checkpoints              │
│  Langfuse (self-hosted) — observability stub (no-op v1) │
└────────────────────────────────────────┘
```

## Modules

`apps/api/src/architect/`:

| Module | Role |
|---|---|
| `agents/common/` | `state.py` (AgentState), `llm.py` (LLMClient + token meter + budget), `tools.py` (typed traversal toolkit), `proposals.py` (decision_log write path), `checkpointer.py` (AsyncPostgresSaver), `tracing.py` (Langfuse stub) |
| `agents/{echo,architect,tickets,reviewer,refactor}/` | Per-agent LangGraphs / analyses |
| `api/` | FastAPI routers — one per endpoint family |
| `graph/` | Neo4j client + idempotent schema (constraints, indexes) |
| `ingest/` | Tree-sitter parsers, cross-file resolver, graph writer, CLI orchestrator |
| `embeddings/` | OpenAI client + pgvector store + cost preflight |
| `migrations/` | Postgres SQL runner (idempotent, tracked in `schema_version`) |
| `sandbox/` | Docker-backed runner with hardening flags + allow-list |
| `evals/` | YAML case loader + runner; `smoke` and `agent` kinds |

## Load-bearing design decisions

These are the choices the rest of the system rests on. Calling them out so future-me doesn't quietly walk them back.

### 1. Agents never emit raw Cypher

Agents use a **typed traversal toolkit** (`find_function`, `callers_of`, `dependents_of`, `subgraph_around`) and **typed proposals** (`propose_node`, `propose_edge`). Each is a parameterized Cypher template; agents pass typed args, never strings. An LLM that hallucinates `MATCH (n) DETACH DELETE n` simply can't reach the driver.

`apply_proposal()` (the only place graph mutations land) further guards with an allow-list of labels (`Service`, `API`, `DBTable`, `Feature`, `InfraComponent`) and rel types (`DEPENDS_ON`, `OWNS`, `CALLS`, `WRITES_TO`, `READS_FROM`, `DEPLOYED_ON`). Anything else is refused.

### 2. Propose-then-approve write path

No agent writes to the live graph. The Architect's `synthesize` step stages each node and edge into `decision_log` (status `proposed`). A human reviews via the Decisions UI; `apply_proposal()` then writes to Neo4j and flips the row to `applied`. Rejections are kept in the log as an audit trail.

### 3. PR Reviewer uses Neo4j 5 multi-database (planned, v2)

In v1, Reviewer runs its rules against the main graph since we haven't implemented re-ingest of changed files yet. The plan reserves Neo4j 5 multi-database (`graph_pr_<id>`) for v2 so PR review can compare a staged graph to main without mutating it.

### 4. LangGraph Postgres checkpointer on a dedicated autocommit connection

`AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which can't live inside a transaction. The app's main connection pool defaults to transactional connections (right call for migrations + cost_log writes), so the saver gets its own `autocommit=True` connection. See `agents/common/checkpointer.py`.

### 5. Cost enforced at the LLM layer

Every Anthropic call is metered into `cost_log` by `_TokenMeterCallback`. Before every LLM call, the agent runs `check_budget()` which queries today's spend against `DAILY_COST_LIMIT_USD` and raises `BudgetExceededError` if breached. The API surfaces this as 429.

### 6. Tree-sitter byte offsets (not char offsets)

`tree-sitter-language-pack` 1.8 ships the new Rust bindings: parser takes `str`, but `byte_range()` is in UTF-8 bytes. Slicing the decoded string by those offsets silently corrupts every identifier after any multibyte character. `text()` (in `ingest/parsers/_common.py`) slices the original bytes, then decodes — see the M1 regression test.

### 7. Polymorphic CALLS targets, module-only IMPORTS

A constructor call to `IngestStats(...)` and a function call to `write_files()` look the same in the source. The writer uses `apoc.merge.node` with a runtime-chosen label: link to a pre-existing `Function`/`Class` if the qname is already known, else create an `:External` placeholder. IMPORTS edges always target `Module` nodes (the resolver only emits module qnames) so they can't collide with Function/Class qnames.

### 8. Sandbox = stdin-piped script, not bind-mounted

Earlier draft bind-mounted a host tmpdir; the rootless container (`nobody:nogroup`) couldn't read host-owned files. v1 pipes the script body via stdin to the interpreter — no mount, no uid drama.

## Data flow: a single ingest

1. `python -m architect.ingest <repo>` walks the filesystem, respecting `.gitignore` and skipping common heavy dirs.
2. For each `.py` / `.ts` / `.tsx` file, the per-language Tree-sitter extractor returns a `ParsedFile` with definitions (functions, classes, methods), imports, and intra-file calls.
3. The cross-file resolver builds a global symbol table from all ParsedFiles, then turns raw call/import names into target qnames with a confidence score (1.0 intra-file / 0.7 cross-file static / 0.5 ambiguous / 0.3 unresolved or external).
4. The graph writer creates `Repo` / `File` / `Module` / `Function` / `Class` nodes and `HAS_FILE` / `IN_MODULE` / `CONTAINS` / `IMPORTS` / `CALLS` edges in batched parameterized Cypher.
5. (Optional) The OpenAI embeddings client hashes each function/class body, checks the `embedding_cache`, embeds only the uncached ones in batches of ≤96, writes vectors to pgvector, and points `node_embedding` rows at the cache.

## Data flow: an Architect run

```
POST /agents/architect
  → /agents/architect router builds an LLMClient + graph
  → LangGraph compiles the 7-node graph with the shared checkpointer
  → run from START:
      clarify         (v1: pass-through)
      retrieve_context (Sonnet — graph + repo summary)
      propose_services (Sonnet — structured output)
      design_data_model (Sonnet — structured output)
      design_apis      (Sonnet — structured output)
      nfr_pass         (Sonnet — structured output)
      synthesize       (Opus — markdown + graph_delta)
  → graph_delta nodes/edges staged into decision_log (status='proposed')
  → response: { proposal, thread_id }
```

The `thread_id` keys the LangGraph checkpoint. A follow-up POST with the same `thread_id` would resume from the prior state.

## Cross-references

- `docs/graph-schema.md` — node + edge contracts, qname conventions, confidence-score key.
- `docs/agent-contracts.md` — each agent's request/response schema and error codes.
- `docs/demo.md` — step-by-step end-to-end walkthrough.

## Known v1 limitations

Listed in README under "Known v1 limitations". The big ones: Python source-root detection (qname mismatch when ingesting from above the package root), Architect's `clarify` is a pass-through, Refactor's `duplicate_logic` analysis is stubbed, Langfuse handler is a no-op.
