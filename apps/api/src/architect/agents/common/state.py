"""Shared LangGraph state for all agents.

Keep it minimal: a message thread (LangGraph's `add_messages` reducer
appends instead of replacing) plus a free-form scratch dict for any
intermediate retrieval results an agent wants to remember within a turn.
Per-thread persistence is the checkpointer's job (see `graph.py`).
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph agent state.

    `total=False` so subclassed states / nodes can elide fields they don't touch.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    scratch: dict[str, Any]
    agent: str  # which agent owns this thread (for cost-log attribution)
    repo: str   # the repo this thread is operating over
