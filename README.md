# AI Autonomous Software Architect

A knowledge-graph-backed AI system that behaves like a senior tech lead: ingests a codebase, models it as a graph, and runs autonomous agents that (1) design architecture from requirements, (2) decompose features into tickets, (3) review PRs against architectural rules, and (4) plan refactors.

The full plan lives at `~/.claude/plans/can-you-create-a-luminous-shell.md`.

## Stack

| Layer | Choice |
|---|---|
| Graph DB | Neo4j 5 |
| Vector store | Postgres 16 + pgvector |
| Code parsing | Tree-sitter (Python + TypeScript) |
| Embeddings | OpenAI `text-embedding-3-large` |
| Agent runtime | LangGraph (Python) |
| Agent LLMs | Claude Sonnet 4.6 default; Opus 4.7 for the Architect synthesis step |
| Tracing | Langfuse (self-hosted via compose) |
| API | FastAPI |
| UI | Vite + React + TypeScript + Tailwind |
| Sandbox | Docker (rootless, network-off) |

## Repo layout

```
apps/
  api/    FastAPI + LangGraph agents (Python, uv)
  web/    Vite + React + TS dashboard
packages/
  schema/ Shared JSON Schemas for agent I/O
docs/     Architecture + graph schema + agent contracts
```

## Quickstart

```bash
cp .env.example .env       # fill in API keys
make up                    # start neo4j + postgres + langfuse
make dev                   # start api + web in parallel
# api: http://localhost:8000   web: http://localhost:5173
```

After M1 lands, ingest a real repo:

```bash
make ingest REPO=~/path/to/some-repo
```

## Status

v1 in active build. See plan for milestones (M0–M6).
