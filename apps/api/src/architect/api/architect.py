"""POST /agents/architect — requirement → architecture proposal + staged graph delta."""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from architect.agents.architect.graph import build_architect_graph, initial_messages
from architect.agents.architect.schemas import ArchitectureProposal
from architect.agents.common.llm import BudgetExceededError, LLMClient
from architect.config import get_settings
from architect.embeddings.store import get_pool

log = structlog.get_logger()
router = APIRouter(prefix="/agents/architect", tags=["agents"])


class ArchitectRequest(BaseModel):
    requirement: str = Field(..., min_length=8, max_length=8000)
    repo: str | None = Field(
        None, description="If set, graph context for this repo is retrieved before designing."
    )
    thread_id: str | None = None


class ArchitectResponse(BaseModel):
    proposal: ArchitectureProposal
    thread_id: str


@router.post("", response_model=ArchitectResponse)
async def architect(request: ArchitectRequest) -> ArchitectResponse:
    settings = get_settings()
    if not settings.active_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No API key configured for AGENT_PROVIDER={settings.agent_provider!r}; "
                "the architect agent cannot run."
            ),
        )
    pool = get_pool()
    client = LLMClient(settings, pool)
    graph = build_architect_graph(client, settings, pool)
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_scratch = {"thread_id": thread_id}
    try:
        result = await graph.ainvoke(
            {
                "messages": initial_messages(request.requirement, request.repo),
                "scratch": initial_scratch,
                "agent": "architect",
                "repo": request.repo or "",
            },
            config=config,
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    raw = result.get("scratch", {}).get("proposal")
    if not raw:
        raise HTTPException(status_code=500, detail="Architect produced no proposal.")
    return ArchitectResponse(proposal=ArchitectureProposal.model_validate(raw), thread_id=thread_id)
