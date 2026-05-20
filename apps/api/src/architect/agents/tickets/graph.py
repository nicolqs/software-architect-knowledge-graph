"""Ticket Decomposition agent.

One-shot LLM call: a feature description (plus optionally a target qname
or module to anchor it in the graph) becomes an ordered list of tickets
with `kind` ∈ {FE, API, DB, tests, observability, rollout}.

Uses LangChain's `with_structured_output` so the model is forced to
return JSON that matches the Ticket schema; no string parsing.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from architect.agents.common.checkpointer import get_checkpointer
from architect.agents.common.llm import LLMClient
from architect.agents.common.state import AgentState

log = structlog.get_logger()

TicketKind = Literal[
    "FE", "API", "DB", "tests", "observability", "rollout", "docs"
]


class Ticket(BaseModel):
    kind: TicketKind = Field(..., description="Discipline this ticket falls under.")
    title: str = Field(..., max_length=120)
    description: str = Field(..., description="Acceptance criteria, in 2-5 short sentences.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Titles of tickets in this batch that must merge first.",
    )
    touches_qnames: list[str] = Field(
        default_factory=list,
        description="Graph qnames the ticket likely modifies — drop the prefix if unsure.",
    )


class TicketList(BaseModel):
    tickets: list[Ticket]


_SYSTEM = SystemMessage(
    content=(
        "You decompose a software feature into an ordered list of tickets that can be parallelised "
        "by discipline. Output STRICTLY matches the TicketList schema. Rules:\n"
        "- Cover all of: DB migration (if any state changes), API, FE, tests, observability, rollout. Skip categories that genuinely don't apply.\n"
        "- Order tickets so 'depends_on' arrows always point earlier in the list.\n"
        "- Each ticket's description must be 2-5 short sentences with concrete acceptance criteria.\n"
        "- 'touches_qnames' should reference existing nodes when the user supplies graph context; otherwise leave it empty."
    )
)


def build_tickets_graph(client: LLMClient) -> Any:
    """Build and compile the ticket decomposition graph."""

    async def decompose(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="tickets")
        structured = model.with_structured_output(TicketList)
        prior = state.get("messages", [])
        result = cast(TicketList, await structured.ainvoke([_SYSTEM, *prior]))
        # Stash the structured result on scratch; the route reads from here.
        scratch = dict(state.get("scratch", {}))
        scratch["tickets"] = result.model_dump()
        return {"scratch": scratch}

    builder: StateGraph[AgentState, AgentState, AgentState] = StateGraph(AgentState)
    builder.add_node("decompose", decompose)
    builder.add_edge(START, "decompose")
    builder.add_edge("decompose", END)
    return builder.compile(checkpointer=get_checkpointer())


__all__ = ["Ticket", "TicketKind", "TicketList", "build_tickets_graph"]


# Helper kept module-level for the API route.
def initial_messages(feature: str, repo: str | None, target_qname: str | None) -> list[Any]:
    parts = [f"Feature to decompose: {feature}"]
    if repo:
        parts.append(f"Target repo (graph): {repo}")
    if target_qname:
        parts.append(f"Anchor qname (entry point or affected node): {target_qname}")
    return [HumanMessage(content="\n\n".join(parts))]
