"""HTTP routes for agents."""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from architect.agents.common.llm import BudgetExceededError, LLMClient
from architect.agents.echo.graph import build_echo_graph
from architect.config import get_settings
from architect.embeddings.store import get_pool

log = structlog.get_logger()
router = APIRouter(prefix="/agents", tags=["agents"])


class EchoRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: str | None = Field(
        None, description="Resume an existing thread. If omitted, a new uuid is allocated."
    )


class EchoResponse(BaseModel):
    response: str
    thread_id: str


@router.post("/echo", response_model=EchoResponse)
async def echo(request: EchoRequest) -> EchoResponse:
    settings = get_settings()
    if not settings.active_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No API key configured for AGENT_PROVIDER={settings.agent_provider!r}; "
                "the echo agent cannot run."
            ),
        )

    client = LLMClient(settings, get_pool())
    graph = build_echo_graph(client)

    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            config=config,
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    last = result["messages"][-1]
    if not isinstance(last, AIMessage):
        # Should never happen — the graph ends on an AIMessage. Guard anyway.
        raise HTTPException(status_code=500, detail="Agent did not produce an AI message.")
    text = last.content if isinstance(last.content, str) else str(last.content)
    return EchoResponse(response=text, thread_id=thread_id)
