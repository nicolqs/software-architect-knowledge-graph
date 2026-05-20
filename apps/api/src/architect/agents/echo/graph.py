"""Echo agent: the smallest possible LangGraph + LLM combination.

Exists to verify the framework end-to-end:
- Budget check fires.
- LLM call goes out via the metered model.
- cost_log row written.
- Checkpointer persists thread state so a follow-up message in the same
  thread sees the prior conversation.

Not a useful agent in its own right — Architect / Tickets / Reviewer /
Refactor follow in M3 and exercise the same plumbing for real.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph

from architect.agents.common.checkpointer import get_checkpointer
from architect.agents.common.llm import LLMClient
from architect.agents.common.state import AgentState

log = structlog.get_logger()

_SYSTEM = SystemMessage(
    content=(
        "You are the Echo Agent — a smoke-test agent for the framework. "
        "Respond briefly (1-2 sentences) and confirm you received the user's message."
    )
)


def build_echo_graph(client: LLMClient) -> Any:
    """Build and compile the echo graph, bound to the shared checkpointer.

    Return type is `Any` because LangGraph's `CompiledStateGraph` isn't a
    public type we can import without churn across minor releases.
    """

    async def respond(state: AgentState) -> dict[str, Any]:
        await client.check_budget()
        model = client.make_model(agent="echo")
        prior = state.get("messages", [])
        response = await model.ainvoke([_SYSTEM, *prior])
        return {"messages": [response]}

    builder: StateGraph[AgentState, AgentState, AgentState] = StateGraph(AgentState)
    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=get_checkpointer())
