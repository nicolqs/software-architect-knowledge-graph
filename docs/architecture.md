# Architecture

Stub — to be filled in M6. See `~/.claude/plans/can-you-create-a-luminous-shell.md` for the source of truth during the build.

## High-level shape

```
UI (Vite/React/TS) → FastAPI → LangGraph agents → { Neo4j, Postgres+pgvector, Langfuse }
                                 ↑
                                 │
                          Tree-sitter ingestion
```

## Key design decisions

1. **Agents never emit raw Cypher.** They use a typed traversal toolkit (`find_function`, `callers_of`, `dependents_of`, `subgraph_around`, `propose_node`, `propose_edge`). Each is a parameterized Cypher template — never string-formatted.
2. **All graph mutations are proposals first.** Write tools stage to a buffer; nothing touches the live graph without human approval through the UI.
3. **PR reviewer uses Neo4j 5 multi-database** (`graph_pr_<id>`) for isolation. The main graph is never mutated by a review.
4. **Project memory uses LangGraph's official Postgres checkpointer** — no custom thread tables.
5. **Cost is enforced at the `LLMClient` layer**, not best-effort. `DAILY_COST_LIMIT_USD` raises `BudgetExceeded` rather than silently overrunning.

## Open docs to write

- `graph-schema.md` — Cypher constraints, indexes, node/edge contracts (M1).
- `agent-contracts.md` — JSON Schemas for each agent's I/O (M3).
