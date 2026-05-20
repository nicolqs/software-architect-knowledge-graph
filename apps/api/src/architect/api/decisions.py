"""GET /decisions, POST /decisions/{id}/review — propose-then-approve UI flow."""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from architect.agents.common.proposals import (
    apply_proposal,
    list_proposals,
    review_proposal,
)
from architect.embeddings.store import get_pool

log = structlog.get_logger()
router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionRow(BaseModel):
    id: int
    agent: str
    action: str
    repo: str | None
    target_qname: str | None
    props: dict[str, Any]
    status: str


class DecisionsResponse(BaseModel):
    decisions: list[DecisionRow]


@router.get("", response_model=DecisionsResponse)
async def list_decisions(
    status: str | None = Query(None, description="proposed | approved | rejected | applied"),
    repo: str | None = Query(None),
    agent: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> DecisionsResponse:
    pool = get_pool()
    rows = await list_proposals(
        pool=pool,
        status=status,  # type: ignore[arg-type]
        repo=repo,
        agent=agent,
        limit=limit,
    )
    return DecisionsResponse(
        decisions=[
            DecisionRow(
                id=r.id,
                agent=r.agent,
                action=r.action,
                repo=r.repo,
                target_qname=r.target_qname,
                props=r.props,
                status=r.status,
            )
            for r in rows
        ]
    )


class ReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reviewer: str = Field(..., min_length=1, max_length=120)
    apply_now: bool = Field(False, description="If true and status='approved', also apply to Neo4j.")


class ReviewResponse(BaseModel):
    id: int
    new_status: str
    applied: bool


@router.post("/{decision_id}/review", response_model=ReviewResponse)
async def review(decision_id: int, body: ReviewRequest) -> ReviewResponse:
    pool = get_pool()
    await review_proposal(
        pool=pool, decision_id=decision_id, status=body.status, reviewer=body.reviewer
    )
    applied = False
    if body.status == "approved" and body.apply_now:
        try:
            applied = await apply_proposal(pool=pool, decision_id=decision_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReviewResponse(
        id=decision_id,
        new_status="applied" if applied else body.status,
        applied=applied,
    )
