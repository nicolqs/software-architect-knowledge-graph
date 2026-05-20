# Demo walkthrough

A scripted ~10-minute run through every part of the system. Assumes `make install` has run.

## Setup (one-time)

```bash
cp .env.example .env
# Edit .env. At minimum:
#   NEO4J_PASSWORD=...     (any value)
#   POSTGRES_PASSWORD=...  (any value)
# For Architect / Tickets / Echo: ANTHROPIC_API_KEY=sk-ant-...
# For ingest embeddings:           OPENAI_API_KEY=sk-...

make up                # Neo4j + Postgres + Langfuse
make ingest REPO=$(pwd) --no-embeddings   # ingest this repo into itself
# (use `make ingest REPO=$(pwd)` without --no-embeddings if you have OPENAI_API_KEY)

make dev               # API on :8000, UI on :5173
```

When the dust settles, open `http://localhost:5173`.

---

## 1. Status (Sidebar → Status)

You should see:
- Backend status `ok`, both `neo4j` and `postgres` up.
- Ingested repos table with `architect-self`, ~50 files, ~130 functions, ~34 classes.

If this works, the whole stack — Neo4j driver, Postgres pool, FastAPI, Vite, the typed API client — is alive.

## 2. Graph viewer (Sidebar → Graph)

- Pick `architect-self`.
- Paste a qname, e.g. `apps.api.src.architect.ingest.pipeline.run_ingest`.
- Depth: 1, click **Load**.

You'll see ~26 nodes / ~31 edges around the orchestrator: `Function` (green), `Class` (blue), `Module` (purple), `External` (gray). The graph is colour-coded by label.

Bump depth to 2 to see the second-hop neighbourhood. Capped per-hop so it stays legible.

## 3. PR Reviewer (Sidebar → Reviewer)

No API key needed. The reviewer is pure graph analytics.

- Repo: `architect-self`.
- Changed files (one per line):
  ```
  apps/api/src/architect/ingest/writer.py
  apps/api/src/architect/ingest/resolver.py
  ```
- **Run review**.

Expect 4-ish `advisory` findings — `missing_tests` for `upsert_repo`, `write_files`, `link_methods_to_classes`, `write_edges`. These functions exist in `writer.py`; no `test_*` function calls them in this repo, so the reviewer surfaces the gap.

Add `critical_circular.py` to the graph to see `circular_import`, or change a high-fanin function (>=10 callers) to see `high_fanin_change`.

## 4. Refactor Planner (Sidebar → Refactor)

No API key needed. Graph analytics → ordered list.

- Repo: `architect-self` → **Run analysis**.

Expect a list of `dead_code` items: functions with 0 incoming `CALLS` edges. Some are real (`today_spent_usd`, `langfuse_handler`), some are LangGraph node functions that aren't statically callable (the `respond` inside `build_echo_graph`), some are false positives from the v1 qname-mismatch limitation.

For each: `kind`, `risk`, `blast_radius`, `rationale`, plus `file_path:line`.

## 5. Tickets (Sidebar → Tickets) — requires ANTHROPIC_API_KEY

- Feature: e.g. "Add a workout-difficulty filter to the dashboard with per-user persistence."
- Optional Repo: `architect-self`.
- **Decompose**.

You'll get an ordered ticket list. Each ticket: `kind` ∈ {FE, API, DB, tests, observability, rollout, docs}, title, description with acceptance criteria, `depends_on` referencing earlier tickets, and `touches_qnames` when the LLM commits to graph nodes.

If the agent runs without an API key, it 503s with a clear "ANTHROPIC_API_KEY is not configured" message — same for Architect and Echo.

## 6. Architect (Sidebar → Architect) — requires ANTHROPIC_API_KEY

The hero. 7-node LangGraph: clarify → retrieve_context → propose_services → design_data_model → design_apis → nfr_pass → synthesize.

- Requirement: "Build a real-time chat system for 50k concurrent users with delivery receipts and offline sync."
- Optional Repo: `architect-self`.
- **Design**.

This runs 6 LLM calls (Sonnet) + 1 final call (Opus for the synthesize step). When it returns:

- Left pane: an RFC-ready architecture markdown — Overview / Services / Data model / APIs / NFRs / Risks.
- Right side: Services / Tables / Endpoints summaries, plus a "Proposed delta" card showing how many nodes + edges were staged into `decision_log` for review.

Tip: budget guardrail. `DAILY_COST_LIMIT_USD` (default $20) is enforced before every LLM call. Hit the limit, you'll get a 429.

## 7. Decisions (Sidebar → Decisions)

If Architect ran in step 6 with a repo, you'll see ~5-30 `proposed` rows here. Each row shows:
- The action (`propose_node` or `propose_edge`)
- The agent that proposed it (`architect`)
- The proposed payload as JSON
- `Approve & apply` / `Approve (don't apply)` / `Reject` buttons.

**Approve & apply** runs `apply_proposal()`: parametrized Cypher, allow-listed labels (`Service`, `API`, `DBTable`, `Feature`, `InfraComponent`) and rel types (`DEPENDS_ON`, `OWNS`, `CALLS`, `WRITES_TO`, `READS_FROM`, `DEPLOYED_ON`). Anything else is refused — the apply path is hostile-input-resistant by design.

After applying, switch the filter to `applied` to see the audit trail. Switch back to the Graph viewer and look up one of the new qnames; it's in the live graph.

## 8. Echo (Sidebar → Echo) — requires ANTHROPIC_API_KEY

Framework smoke-test agent. Send a message, get a 1-2 sentence reply.

Each turn:
- `check_budget()` queries `cost_log` for today's spend.
- LLM is invoked with the metering callback attached.
- The callback writes one row to `cost_log` keyed by (agent, model, tokens, cost).
- The checkpointer persists the thread to Postgres. The `thread_id` shown at the bottom is the resume key.

Send a second message — the agent sees the prior turn in state because the checkpointer reloaded it.

## 9. Sandbox

The sandbox isn't in the UI for v1 (it's an internal validation tool for Architect / Refactor). Exercise it via the API:

```bash
curl -X POST http://localhost:8000/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"image":"alpine:3.20","script":"echo hello-from-sandbox"}'
```

You should see `{"exit_code":0,"stdout":"hello-from-sandbox\n",...}`.

Try `wget -q -T 3 -O - https://example.com || echo BLOCKED` — the network is off; you'll see `BLOCKED`. Try `sleep 30` with `"timeout_s": 2` — `timed_out: true` and `duration_s < 5`.

## 10. Eval harness

```bash
make eval
```

Runs every YAML case under `apps/api/evals/cases/*.yml`. Smoke cases pass without LLM (graph builds; reviewer + refactor run analyses). Agent cases skip cleanly when `ANTHROPIC_API_KEY` is empty — `make eval` exits 0 either way.

## Teardown

```bash
make down            # stop infra (keeps volumes — data persists)
docker volume rm \
  software-architect-knowledge-graph_neo4j_data \
  software-architect-knowledge-graph_postgres_data \
  software-architect-knowledge-graph_neo4j_logs   # if you want a clean slate
```
