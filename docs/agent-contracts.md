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

## Future agents (M3)

`Architect`, `Tickets`, `Reviewer`, `Refactor` will follow the same convention:

- One POST route under `/agents/<name>`.
- Pydantic request + response models.
- `thread_id` support via the shared Postgres checkpointer.
- The same `429` / `503` semantics on budget / config failures.

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
