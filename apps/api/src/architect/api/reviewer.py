"""POST /agents/reviewer — graph-rules-based PR review."""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from architect.agents.reviewer.checks import Finding, run_checks

log = structlog.get_logger()
router = APIRouter(prefix="/agents/reviewer", tags=["agents"])


class ReviewRequest(BaseModel):
    repo: str = Field(..., description="The ingested repo name in the graph.")
    changed_files: list[str] = Field(
        ..., description="Paths (posix, relative to repo root) the PR touches.", min_length=1
    )


class ReviewFinding(BaseModel):
    severity: str
    rule: str
    message: str
    qname: str | None = None
    file_path: str | None = None
    line: int | None = None


class ReviewResponse(BaseModel):
    repo: str
    findings: list[ReviewFinding]
    summary: dict[str, int]


def _to_pydantic(finding: Finding) -> ReviewFinding:
    return ReviewFinding(
        severity=finding.severity,
        rule=finding.rule,
        message=finding.message,
        qname=finding.qname,
        file_path=finding.file_path,
        line=finding.line,
    )


@router.post("", response_model=ReviewResponse)
async def review(request: ReviewRequest) -> ReviewResponse:
    raw = await run_checks(request.repo, request.changed_files)
    counts = {"critical": 0, "important": 0, "advisory": 0}
    for f in raw:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return ReviewResponse(
        repo=request.repo,
        findings=[_to_pydantic(f) for f in raw],
        summary=counts,
    )
