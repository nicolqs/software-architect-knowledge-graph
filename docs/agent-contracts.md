# Agent contracts

Each agent exposes a typed request + response so the UI can render any agent generically and the eval harness can wire up assertions without hand-coding per agent.

For v1 the contracts live as Pydantic models in `apps/api/src/architect/api/agents.py` rather than separate JSON Schema files — FastAPI emits the OpenAPI schema automatically, and `apps/web/src/lib/api.ts` can be regenerated via `openapi-typescript` whenever the contracts change. We'll graduate them into `packages/schema/*.json` when the second consumer (the eval runner UI, maybe) shows up.

## Echo (M2)

The smoke-test agent that verifies the framework wiring.

### Request

```ts
{
  message: string;        // 1..8000 chars
  thread_id?: string;     // omit to start a new thread; pass to resume
}
```

### Response

```ts
{
  response: string;       // the agent's reply
  thread_id: string;      // echoed back; persistent across turns via the Postgres checkpointer
}
```

### Errors

- `503` — `ANTHROPIC_API_KEY` not configured.
- `429` — daily LLM budget (`DAILY_COST_LIMIT_USD`) exceeded.

## Architect (M3)

7-node LangGraph (`clarify → retrieve_context → propose_services → design_data_model → design_apis → nfr_pass → synthesize`). Synthesize uses Opus; the rest use Sonnet.

### Request

```ts
{
  requirement: string;        // 8..8000 chars
  repo?: string;              // optional: pull graph context from this ingested repo
  thread_id?: string;
}
```

### Response

```ts
{
  proposal: {
    services: ProposedService[];
    tables: ProposedTable[];
    endpoints: ProposedEndpoint[];
    nfrs: NfrConcern[];
    markdown: string;         // PR/RFC-ready architecture doc
    graph_delta: {
      nodes: { label, qname, props }[];
      edges: { from_qname, to_qname, rel_type, props }[];
    };
  };
  thread_id: string;
}
```

Side effect: when `repo` is set, the `graph_delta` is staged into `decision_log` (status `proposed`). A human approves via the M4 UI before any Neo4j write.

## Tickets (M3)

Single-call LLM with `with_structured_output(TicketList)`.

### Request

```ts
{ feature: string; repo?: string; target_qname?: string; thread_id?: string; }
```

### Response

```ts
{
  tickets: {
    kind: "FE" | "API" | "DB" | "tests" | "observability" | "rollout" | "docs";
    title: string;
    description: string;
    depends_on: string[];       // titles of earlier tickets in this batch
    touches_qnames: string[];   // graph nodes the ticket modifies, when known
  }[];
  thread_id: string;
}
```

## Reviewer (M3) — no LLM required

Runs deterministic graph checks against the ingested repo. Critical / important / advisory findings sorted in that order.

### Request

```ts
{ repo: string; changed_files: string[]; }   // changed_files is posix paths
```

### Response

```ts
{
  repo: string;
  findings: {
    severity: "critical" | "important" | "advisory";
    rule: string;
    message: string;
    qname?: string;
    file_path?: string;
    line?: number;
  }[];
  summary: { critical: number; important: number; advisory: number };
}
```

v1 rules: `circular_import`, `high_fanin_change` (≥10 callers), `low_confidence_callers` (<0.5), `missing_tests`.

## Refactor (M3) — no LLM required

Graph analytics: dead code + high-coupling modules. Duplicate-logic clustering is stubbed pending pgvector embeddings.

### Request

```ts
{ repo: string; }
```

### Response

```ts
{
  repo: string;
  items: {
    kind: "dead_code" | "high_coupling" | "duplicate_logic";
    qname: string;
    title: string;
    rationale: string;
    risk: "low" | "medium" | "high";
    blast_radius: number;
    file_path?: string;
    line?: number;
  }[];
  summary: Record<kind, number>;
}
```

## Decision-log write path

Every graph mutation an agent proposes lands as a row in `decision_log` with `status='proposed'`. The UI (M4) will let a human flip it to `approved` or `rejected`; an applier then writes the mutation to Neo4j and marks the row `applied`. Allowed labels: `Service`, `API`, `DBTable`, `Feature`, `InfraComponent`. Allowed edge types: `DEPENDS_ON`, `OWNS`, `CALLS`, `WRITES_TO`, `READS_FROM`, `DEPLOYED_ON`.

## Tool safety

Agents have access to the typed traversal toolkit (`architect.agents.common.tools`). They NEVER emit raw Cypher. All write operations route through the `decision_log` table (status `proposed`) and require a human approval step before reaching the live graph. See `docs/architecture.md` for the rationale.

## Eval contract

Eval cases under `apps/api/evals/cases/*.yml` use this minimal schema:

```yaml
name: <kebab-case-id>     # required
kind: smoke | agent       # required
agent: echo | ...         # required
description: free text    # optional
input:                    # required for `kind: agent`
  message: "..."
assertions:               # required for `kind: agent`
  - kind: contains_any
    of: ["a", "b"]
```

Currently supported assertion kinds: `contains_any`. More will be added as agents and eval needs grow.
