"""POST /agents/tickets — feature → ordered ticket list."""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from architect.agents.common.llm import BudgetExceededError, LLMClient
from architect.agents.tickets.graph import (
    Ticket,
    TicketList,
    build_tickets_graph,
    initial_messages,
)
from architect.config import get_settings
from architect.embeddings.store import get_pool

log = structlog.get_logger()
router = APIRouter(prefix="/agents/tickets", tags=["agents"])


class TicketsRequest(BaseModel):
    feature: str = Field(..., min_length=4, max_length=4000)
    repo: str | None = None
    target_qname: str | None = None
    thread_id: str | None = None


class TicketsResponse(BaseModel):
    tickets: list[Ticket]
    thread_id: str


@router.post("", response_model=TicketsResponse)
async def tickets(request: TicketsRequest) -> TicketsResponse:
    settings = get_settings()
    if not settings.active_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No API key configured for AGENT_PROVIDER={settings.agent_provider!r}; "
                "the tickets agent cannot run."
            ),
        )
    client = LLMClient(settings, get_pool())
    graph = build_tickets_graph(client)
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await graph.ainvoke(
            {
                "messages": initial_messages(request.feature, request.repo, request.target_qname),
                "scratch": {},
            },
            config=config,
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    raw = result.get("scratch", {}).get("tickets")
    if not raw:
        raise HTTPException(status_code=500, detail="Agent produced no tickets.")
    parsed = TicketList.model_validate(raw)
    return TicketsResponse(tickets=parsed.tickets, thread_id=thread_id)
