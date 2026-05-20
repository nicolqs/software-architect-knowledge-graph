"""Eval harness — runs YAML cases through agents and reports pass/fail.

Design:
- Cases live under `apps/api/evals/cases/*.yml`.
- A case has a `kind` (`smoke` or `agent`) and a list of `assertions`.
- `smoke` cases don't need any external service; they exercise framework
  wiring (import the graph, build it, do not call the LLM). Always run.
- `agent` cases call the LLM. Skipped (not failed) when ANTHROPIC_API_KEY
  is empty so `make eval` exits 0 on a fresh machine.
- A skipped case is reported but doesn't fail the run.
- Any actual assertion failure exits the process with code 1.

Run with `make eval` or `uv run python -m architect.evals.runner`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml
from langchain_core.messages import AIMessage, HumanMessage

from architect.agents.architect.graph import build_architect_graph
from architect.agents.common.checkpointer import close_checkpointer, init_checkpointer
from architect.agents.common.llm import LLMClient
from architect.agents.echo.graph import build_echo_graph
from architect.agents.refactor.analyses import plan_refactors
from architect.agents.reviewer.checks import run_checks
from architect.agents.tickets.graph import build_tickets_graph
from architect.config import get_settings
from architect.embeddings import store as embed_store
from architect.graph import client as graph_client
from architect.migrations import run_migrations

log = structlog.get_logger()

CASES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "evals" / "cases"


@dataclass(slots=True)
class CaseResult:
    name: str
    status: str  # 'pass' | 'fail' | 'skip'
    detail: str = ""


def _load_cases() -> list[dict[str, Any]]:
    if not CASES_DIR.exists():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        with path.open() as f:
            doc = yaml.safe_load(f)
        if not isinstance(doc, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        doc.setdefault("name", path.stem)
        cases.append(doc)
    return cases


def _assert_contains_any(text: str, options: list[str]) -> tuple[bool, str]:
    lower = text.lower()
    matches = [o for o in options if o.lower() in lower]
    if matches:
        return True, f"matched {matches[0]!r}"
    return False, f"expected one of {options!r}, got {text[:120]!r}"


async def _run_smoke(case: dict[str, Any]) -> CaseResult:
    """Smoke checks verify framework wiring without calling the LLM.

    For LangGraph agents: assert the graph builds. For analysis agents
    (reviewer, refactor): actually run the analysis against the supplied
    repo so a graph regression surfaces here, not later.
    """
    agent = case.get("agent", "echo")
    settings = get_settings()
    pool = embed_store.get_pool()
    try:
        if agent == "echo":
            build_echo_graph(LLMClient(settings, pool))
            return CaseResult(name=case["name"], status="pass", detail="echo graph built")
        if agent == "tickets":
            build_tickets_graph(LLMClient(settings, pool))
            return CaseResult(name=case["name"], status="pass", detail="tickets graph built")
        if agent == "architect":
            build_architect_graph(LLMClient(settings, pool), settings, pool)
            return CaseResult(name=case["name"], status="pass", detail="architect graph built")
        if agent == "reviewer":
            inp = case.get("input") or {}
            findings = await run_checks(inp["repo"], inp.get("changed_files") or [])
            return CaseResult(
                name=case["name"],
                status="pass",
                detail=f"reviewer ran; {len(findings)} findings",
            )
        if agent == "refactor":
            inp = case.get("input") or {}
            items = await plan_refactors(inp["repo"])
            return CaseResult(
                name=case["name"],
                status="pass",
                detail=f"refactor planner ran; {len(items)} items",
            )
    except Exception as exc:
        return CaseResult(name=case["name"], status="fail", detail=f"smoke failed: {exc}")
    return CaseResult(name=case["name"], status="fail", detail=f"unknown smoke agent: {agent!r}")


async def _run_agent(case: dict[str, Any]) -> CaseResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return CaseResult(
            name=case["name"],
            status="skip",
            detail="ANTHROPIC_API_KEY not set",
        )
    if case.get("agent") != "echo":
        return CaseResult(
            name=case["name"],
            status="skip",
            detail=f"agent {case.get('agent')!r} not implemented yet",
        )
    msg = case["input"]["message"]
    client = LLMClient(settings, embed_store.get_pool())
    graph = build_echo_graph(client)
    config = {"configurable": {"thread_id": f"eval-{case['name']}"}}
    result = await graph.ainvoke({"messages": [HumanMessage(content=msg)]}, config=config)
    last = result["messages"][-1]
    text = last.content if isinstance(last, AIMessage) and isinstance(last.content, str) else str(last)

    for assertion in case.get("assertions", []):
        kind = assertion.get("kind")
        if kind == "contains_any":
            ok, detail = _assert_contains_any(text, assertion["of"])
            if not ok:
                return CaseResult(name=case["name"], status="fail", detail=detail)
        else:
            return CaseResult(
                name=case["name"], status="fail", detail=f"unknown assertion kind: {kind}"
            )
    return CaseResult(name=case["name"], status="pass", detail=text[:80])


async def _setup() -> None:
    settings = get_settings()
    graph_client.init_driver(settings)
    await embed_store.init_pool(settings)
    pool = embed_store.get_pool()
    async with pool.connection() as conn:
        await run_migrations(conn)
    await init_checkpointer(settings)


async def _teardown() -> None:
    await close_checkpointer()
    await graph_client.close_driver()
    await embed_store.close_pool()


async def main_async() -> int:
    cases = _load_cases()
    if not cases:
        print("No eval cases found at", CASES_DIR)
        return 0

    try:
        await _setup()
    except Exception as exc:
        print(f"[setup] failed: {exc}")
        return 2

    results: list[CaseResult] = []
    try:
        for case in cases:
            kind = case.get("kind", "agent")
            if kind == "smoke":
                results.append(await _run_smoke(case))
            elif kind == "agent":
                results.append(await _run_agent(case))
            else:
                results.append(
                    CaseResult(name=case["name"], status="fail", detail=f"unknown kind: {kind}")
                )
    finally:
        await _teardown()

    passed = sum(1 for r in results if r.status == "pass")
    skipped = sum(1 for r in results if r.status == "skip")
    failed = sum(1 for r in results if r.status == "fail")

    print()
    for r in results:
        glyph = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[r.status]
        print(f"  [{glyph}] {r.name} — {r.detail}")
    print()
    print(f"Total: {len(results)}  pass: {passed}  skip: {skipped}  fail: {failed}")
    return 1 if failed else 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
