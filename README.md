# AI Autonomous Software Architect

A knowledge-graph-backed AI system that behaves like a senior tech lead. Ingest a codebase; the graph models its services, modules, functions, calls, and imports. Then run five agents over it:

| Agent | What it does | Needs LLM? |
|---|---|---|
| **Architect** | Requirements → architecture (services + tables + APIs + NFRs) + a staged graph delta you can approve | Yes (Sonnet + Opus) |
| **Tickets** | Feature description → ordered ticket list (FE / API / DB / tests / observability / rollout) | Yes (Sonnet) |
| **Reviewer** | PR-style audit against the graph: circular imports, high-fanin changes, low-confidence callers, missing tests | No |
| **Refactor** | Plan: dead code, high-coupling modules, ordered by blast radius | No |
| **Echo** | Framework smoke-test agent | Yes |

Reviewer and Refactor produce useful output without any LLM — they're pure graph analytics over the ingested repo.

## Status

v1 complete. M0 → M6 from the plan are all in. See `git log` — one feat commit per milestone, plus a couple of `fix(...)` commits for issues caught during milestone testing.

## Stack

| Layer | Choice |
|---|---|
| Graph DB | Neo4j 5 + APOC |
| Vector store | Postgres 16 + pgvector |
| Code parsing | Tree-sitter (Python + TypeScript) via `tree-sitter-language-pack` |
| Embeddings | OpenAI `text-embedding-3-large` (truncated to 1536 dims) |
| Agent runtime | LangGraph 1.x with Postgres checkpointer |
| Agent LLMs | Claude Sonnet 4.6 default; Opus 4.7 for the Architect's synthesize step |
| API | FastAPI + uv |
| UI | Vite + React 18 + TS + Tailwind + `@xyflow/react` |
| Sandbox | Docker (rootless, `--network=none`, `--cap-drop=ALL`, time + mem limits) |

## Quickstart

```bash
# Once: install deps for every workspace
make install

# Bring up Neo4j + Postgres + Langfuse (Docker)
make up

# Copy and edit secrets
cp .env.example .env
# At minimum set NEO4J_PASSWORD + POSTGRES_PASSWORD. For agent LLM calls:
# ANTHROPIC_API_KEY=... For embeddings (optional): OPENAI_API_KEY=...

# Ingest a repo. Skip embeddings if no OpenAI key:
make ingest REPO=/path/to/some-repo
# or:
cd apps/api && uv run python -m architect.ingest /path/to/some-repo --no-embeddings

# Start API + UI in parallel
make dev
# → API: http://localhost:8000   UI: http://localhost:5173
```

If port 7474/7687/5432/3001 collide with other local services, override them in your `.env` — see `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT`, `POSTGRES_PORT`, `LANGFUSE_PORT` in `.env.example`.

## Demo

See [`docs/demo.md`](docs/demo.md) for a step-by-step walkthrough hitting every agent.

Short version: ingest this repo into itself with `make ingest REPO=$(pwd)`, then open `localhost:5173` and click through:

- **Status** — backend health + ingested repo counts.
- **Graph** — pick `architect-self` + `apps.api.src.architect.ingest.pipeline.run_ingest`, see a 1-hop subgraph.
- **Reviewer** — paste `apps/api/src/architect/ingest/writer.py` as changed files; get findings.
- **Refactor** — pick `architect-self`; get a dead-code + high-coupling plan.
- **Tickets / Architect** — need `ANTHROPIC_API_KEY`. Architect's `synthesize` step also stages a graph delta into `decision_log`, surfaced under **Decisions**.

## Repo layout

```
apps/
  api/           # FastAPI + LangGraph agents (Python, uv)
    src/architect/
      agents/    # architect, tickets, reviewer, refactor, echo + common/
      api/       # FastAPI routers (agents, graph, decisions, sandbox)
      embeddings/, graph/, ingest/, migrations/, sandbox/, evals/
    evals/cases/ # YAML eval cases
    tests/       # pytest (unit + live-Postgres/Neo4j/Docker integration)
  web/           # Vite + React + TS dashboard
docs/            # architecture.md, graph-schema.md, agent-contracts.md, demo.md
infra/postgres/  # init.sql (pgvector extension, langfuse schema)
```

## Make targets

| Target | What |
|---|---|
| `make install` | Install all deps (root pnpm + api uv + web pnpm) |
| `make up` / `make down` / `make logs` / `make ps` | Manage local infra |
| `make dev` | Run API + UI in parallel |
| `make ingest REPO=...` | Ingest a repo into the graph |
| `make test` | Run api + web tests |
| `make eval` | Run the agent eval harness |
| `make lint` / `make typecheck` | Code-quality gates |

## Key design decisions

Documented in detail under `docs/`. A few that are easy to miss:

1. **Agents never emit raw Cypher.** They use a typed traversal toolkit (`find_function`, `callers_of`, `dependents_of`, `subgraph_around`). Each is a parameterized template. An LLM that hallucinates `MATCH (n) DETACH DELETE n` can't reach the graph.
2. **All graph mutations are proposals first.** Architect's `synthesize` step stages every node/edge into `decision_log` (status `proposed`). A human flips it to `approved` via the Decisions UI; only then does `apply_proposal` touch Neo4j. Apply uses an allow-list of labels and rel types.
3. **PR Reviewer is LLM-free** and uses Cypher rules against the graph. Predictable, cheap, fast.
4. **Cost is enforced**, not best-effort. `DAILY_COST_LIMIT_USD` is checked before every LLM call. `BudgetExceededError` surfaces as a 429.
5. **Sandbox executes untrusted code under** `--network=none --read-only --cap-drop=ALL --user 65534:65534` with wall-clock + memory + pid limits, and only images in an allow-list.

## Known v1 limitations

- Architect's `clarify` node is a pass-through; multi-turn clarification needs LangGraph `interrupt()` + the UI to handle a question-and-resume flow.
- Refactor's `duplicate_logic` analysis is stubbed — needs vector clustering on the function-body embeddings, which requires `OPENAI_API_KEY` set at ingest time.
- Langfuse handler is a no-op stub; instrumentation will land when we're calling LLMs in earnest.
- The Refactor planner's `_is_framework_invoked` filter treats any function under `*/api/*.py` as a route handler — true for this repo's layout, will under-report dead code in repos where `api/` is a generic helpers module. Proper fix is decorator extraction at parse time; deferred to v2.
- `/sandbox/run` has no auth in v1 — fine for `localhost` dev, but add auth before exposing the API beyond the local machine.

## License

[MIT](LICENSE) — © 2026 Nicolas Vincent
