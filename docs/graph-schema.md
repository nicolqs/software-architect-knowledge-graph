# Graph schema (Neo4j)

The graph models a codebase's structure. Agents query it via a **typed traversal toolkit** — never raw Cypher (see `docs/architecture.md`).

## Nodes

| Label | Required props | Optional props | Notes |
|---|---|---|---|
| `Repo` | `name` | `path`, `ingested_at`, `commit_sha` | Unique by `name`. |
| `File` | `repo`, `path` | `language`, `content_hash`, `loc` | Unique by `(repo, path)`. |
| `Module` | `repo`, `qname` | `path` | Unique by `(repo, qname)`. A logical grouping; for Python = package/module path, for TS = a directory or barrel file. |
| `Function` | `repo`, `qname`, `name` | `file_path`, `line`, `signature`, `is_async` | Unique by `(repo, qname)`. |
| `Class` | `repo`, `qname`, `name` | `file_path`, `line` | Unique by `(repo, qname)`. |

**Qualified names (qname):**
- Python: `package.module.Class.method` or `package.module.function`.
- TypeScript: `path/to/file::ClassName::methodName` (path relative to repo root, no extension).

## Edges

| Type | From → To | Props | Meaning |
|---|---|---|---|
| `HAS_FILE` | `Repo` → `File` | — | Containment. |
| `IN_MODULE` | `File` → `Module` | — | The module/package a file belongs to. |
| `CONTAINS` | `File` → `Function`/`Class` | — | Top-level definitions in a file. |
| `CONTAINS` | `Class` → `Function` | — | Methods. |
| `IMPORTS` | `File` → `Module`/`Function`/`Class` | `confidence` | Source of an import statement to its target (intra-repo when resolvable). |
| `CALLS` | `Function` → `Function` | `confidence`, `count` | Static or inferred call. |
| `DEPENDS_ON` | `Module` → `Module` | — | Aggregated from `IMPORTS`. |

### Confidence scores

A float in `[0, 1]` on `IMPORTS` and `CALLS` edges:

- **1.0** — static, intra-file (same source file).
- **0.7** — static, cross-file via a resolvable import in the same repo.
- **0.3** — inferred / dynamic dispatch / unresolved target.

PR reviewer treats `< 0.5` edges as advisory only.

## Constraints + indexes

See `apps/api/src/architect/graph/schema.py`. All idempotent (`IF NOT EXISTS`). Applied at API startup and at the top of `python -m architect.ingest`.

## Out of scope (v1)

- Cross-repo edges (multi-repo federation is v2).
- Runtime call edges (we model static structure only).
- Type-level relationships (`IMPLEMENTS_INTERFACE`, `EXTENDS`) — easy to add later; not needed for the v1 agents.
