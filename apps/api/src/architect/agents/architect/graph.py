"""Architect agent — the hero.

Seven-node LangGraph that turns a natural-language requirement into a full
architecture proposal + a graph delta the user can approve into the live
graph via `decision_log`.

Nodes:
1. clarify          — skip in v1 (placeholder; LangGraph interrupt() lands in v2).
2. retrieve_context — graph + vector lookup if a `repo` is supplied.
3. propose_services — list of services with responsibilities.
4. design_data_model — DB tables per service.
5. design_apis      — endpoints per service.
6. nfr_pass         — scaling / observability / security concerns.
7. synthesize       — Opus call. Produces markdown + graph_delta.

Models: Sonnet for nodes 2-6; Opus for synthesize (depth of reasoning
justifies the price for a one-shot architecture call).
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from psycopg_pool import AsyncConnectionPool

from architect.agents.architect.schemas import (
    ArchitectureProposal,
    NfrConcern,
    ProposedEndpoint,
    ProposedGraphDelta,
    ProposedService,
    ProposedTable,
)
from architect.agents.common.checkpointer import get_checkpointer
from architect.agents.common.llm import LLMClient
from architect.agents.common.proposals import propose_edge, propose_node
from architect.agents.common.state import AgentState
from architect.config import Settings

log = structlog.get_logger()


_SYS_RETRIEVE = SystemMessage(
    content=(
        "You are the Architect agent's retrieval step. Summarise relevant existing services "
        "or modules in the user's repo that the new design should integrate with. If no repo "
        "is provided, output a single line: 'No repo context.'"
    )
)
_SYS_SERVICES = SystemMessage(
    content=(
        "Propose 3-7 services for the requirement. Each service has a single layer "
        "and 2-5 responsibilities. depends_on must reference services in this same list."
    )
)
_SYS_TABLES = SystemMessage(
    content=(
        "Propose database tables for the services. Every table is owned by exactly one service. "
        "Columns include id (PK) where appropriate. Use snake_case. Add indexes the obvious "
        "query patterns require (lookups by user_id, timestamps, etc.)."
    )
)
_SYS_APIS = SystemMessage(
    content=(
        "Propose REST API endpoints exposed by each service. Keep paths versioned (/v1/...). "
        "Include 'summary' that fits in a single PR line. response_shape and request_shape are "
        "one-line schema sketches; not full OpenAPI."
    )
)
_SYS_NFRS = SystemMessage(
    content=(
        "List 3-8 non-functional concerns covering scaling, observability, security, reliability, "
        "and cost. For each: a one-sentence concern and a one-sentence mitigation."
    )
)
_SYS_SYNTHESIZE = SystemMessage(
    content=(
        "You are the Architect's final synthesis step. Compose a single markdown document "
        "ready to paste into a PR description, with sections: Overview, Services, Data model, "
        "APIs, Non-functional requirements, Risks. Then return graph_delta entries the user "
        "can stage into their knowledge graph (label ∈ {Service, API, DBTable, InfraComponent, "
        "Feature} for nodes; rel_type ∈ {DEPENDS_ON, OWNS, WRITES_TO, READS_FROM} for edges)."
    )
)


def build_architect_graph(client: LLMClient, settings: Settings, pool: AsyncConnectionPool) -> Any:
    """Build and compile the architect graph."""

    async def clarify(state: AgentState) -> dict[str, Any]:
        # v1: pass-through. The interrupt-based clarify loop lands when the
        # UI can render a question-and-resume flow.
        return {}

    async def retrieve_context(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="architect")
        response = await model.ainvoke([_SYS_RETRIEVE, *state.get("messages", [])])
        scratch = dict(state.get("scratch", {}))
        text = response.content if isinstance(response.content, str) else str(response.content)
        scratch["context"] = text
        return {"scratch": scratch, "messages": [AIMessage(content=text)]}

    async def propose_services(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="architect").with_structured_output(
            list[ProposedService]
        )
        services = cast(
            list[ProposedService],
            await model.ainvoke([_SYS_SERVICES, *state.get("messages", [])]),
        )
        scratch = dict(state.get("scratch", {}))
        scratch["services"] = [s.model_dump() for s in services]
        return {"scratch": scratch}

    async def design_data_model(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="architect").with_structured_output(
            list[ProposedTable]
        )
        tables = cast(
            list[ProposedTable],
            await model.ainvoke(
                [
                    _SYS_TABLES,
                    *state.get("messages", []),
                    AIMessage(content=f"Services so far: {state.get('scratch', {}).get('services')}"),
                ]
            ),
        )
        scratch = dict(state.get("scratch", {}))
        scratch["tables"] = [t.model_dump() for t in tables]
        return {"scratch": scratch}

    async def design_apis(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="architect").with_structured_output(
            list[ProposedEndpoint]
        )
        endpoints = cast(
            list[ProposedEndpoint],
            await model.ainvoke(
                [
                    _SYS_APIS,
                    *state.get("messages", []),
                    AIMessage(content=f"Services: {state.get('scratch', {}).get('services')}"),
                ]
            ),
        )
        scratch = dict(state.get("scratch", {}))
        scratch["endpoints"] = [e.model_dump() for e in endpoints]
        return {"scratch": scratch}

    async def nfr_pass(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="architect").with_structured_output(
            list[NfrConcern]
        )
        nfrs = cast(
            list[NfrConcern],
            await model.ainvoke([_SYS_NFRS, *state.get("messages", [])]),
        )
        scratch = dict(state.get("scratch", {}))
        scratch["nfrs"] = [n.model_dump() for n in nfrs]
        return {"scratch": scratch}

    async def synthesize(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        # Opus for the deep-reasoning step. One call per architect run; the
        # plan's cost guardrail explicitly carves this out.
        model = client.make_model(
            agent="architect", model_name=settings.agent_model_architect
        ).with_structured_output(ArchitectureProposal)
        scratch = state.get("scratch", {})
        context_msg = AIMessage(
            content=(
                "Aggregate everything below into the final ArchitectureProposal.\n\n"
                f"Services: {scratch.get('services')}\n"
                f"Tables: {scratch.get('tables')}\n"
                f"Endpoints: {scratch.get('endpoints')}\n"
                f"NFRs: {scratch.get('nfrs')}\n"
                f"Repo context: {scratch.get('context')}"
            )
        )
        proposal = cast(
            ArchitectureProposal,
            await model.ainvoke(
                [_SYS_SYNTHESIZE, *state.get("messages", []), context_msg]
            ),
        )

        # Stage the graph delta as decision_log proposals. The user approves
        # them later via the UI before they touch Neo4j.
        repo = state.get("repo", "")
        thread_id = (state.get("scratch") or {}).get("thread_id")
        if repo:
            await _stage_delta(
                pool=pool,
                repo=repo,
                thread_id=thread_id,
                delta=proposal.graph_delta,
            )

        scratch = dict(scratch)
        scratch["proposal"] = proposal.model_dump()
        return {"scratch": scratch}

    builder: StateGraph[AgentState, AgentState, AgentState] = StateGraph(AgentState)
    builder.add_node("clarify", clarify)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("propose_services", propose_services)
    builder.add_node("design_data_model", design_data_model)
    builder.add_node("design_apis", design_apis)
    builder.add_node("nfr_pass", nfr_pass)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "clarify")
    builder.add_edge("clarify", "retrieve_context")
    builder.add_edge("retrieve_context", "propose_services")
    builder.add_edge("propose_services", "design_data_model")
    builder.add_edge("design_data_model", "design_apis")
    builder.add_edge("design_apis", "nfr_pass")
    builder.add_edge("nfr_pass", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile(checkpointer=get_checkpointer())


async def _stage_delta(
    *,
    pool: AsyncConnectionPool,
    repo: str,
    thread_id: str | None,
    delta: ProposedGraphDelta,
) -> None:
    """Translate a ProposedGraphDelta into decision_log rows."""
    for node in delta.nodes:
        label = node.get("label")
        qname = node.get("qname")
        if not label or not qname:
            continue
        await propose_node(
            pool=pool,
            agent="architect",
            thread_id=thread_id,
            repo=repo,
            label=label,
            qname=qname,
            props=node.get("props", {}),
        )
    for edge in delta.edges:
        from_q = edge.get("from_qname")
        to_q = edge.get("to_qname")
        rel = edge.get("rel_type")
        if not (from_q and to_q and rel):
            continue
        await propose_edge(
            pool=pool,
            agent="architect",
            thread_id=thread_id,
            repo=repo,
            from_qname=from_q,
            to_qname=to_q,
            rel_type=rel,
            props=edge.get("props", {}),
        )


def initial_messages(requirement: str, repo: str | None) -> list[Any]:
    parts = [f"Requirement: {requirement}"]
    if repo:
        parts.append(f"Target repo: {repo}")
    return [HumanMessage(content="\n\n".join(parts))]


__all__ = ["build_architect_graph", "initial_messages"]
