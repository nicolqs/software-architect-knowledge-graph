"""POST /agents/refactor — graph-analytics-based refactor planner."""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from architect.agents.refactor.analyses import RefactorItem, plan_refactors

log = structlog.get_logger()
router = APIRouter(prefix="/agents/refactor", tags=["agents"])


class RefactorRequest(BaseModel):
    repo: str = Field(..., description="The ingested repo name in the graph.")


class RefactorPlanItem(BaseModel):
    kind: str
    qname: str
    title: str
    rationale: str
    risk: str
    blast_radius: int
    file_path: str | None = None
    line: int | None = None


class RefactorResponse(BaseModel):
    repo: str
    items: list[RefactorPlanItem]
    summary: dict[str, int]


def _to_pydantic(item: RefactorItem) -> RefactorPlanItem:
    return RefactorPlanItem(
        kind=item.kind,
        qname=item.qname,
        title=item.title,
        rationale=item.rationale,
        risk=item.risk,
        blast_radius=item.blast_radius,
        file_path=item.file_path,
        line=item.line,
    )


@router.post("", response_model=RefactorResponse)
async def refactor(request: RefactorRequest) -> RefactorResponse:
    raw = await plan_refactors(request.repo)
    counts: dict[str, int] = {}
    for item in raw:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return RefactorResponse(
        repo=request.repo,
        items=[_to_pydantic(i) for i in raw],
        summary=counts,
    )
