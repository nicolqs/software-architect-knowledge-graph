"""POST /sandbox/run — execute a snippet in a hardened ephemeral container."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from architect.sandbox.runner import (
    SandboxError,
    SandboxRequest,
    docker_available,
)
from architect.sandbox.runner import run as sandbox_run

log = structlog.get_logger()
router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class SandboxRunRequest(BaseModel):
    """Request payload for /sandbox/run.

    NOTE: this endpoint executes (heavily sandboxed) code in a container.
    It must be behind auth before being exposed beyond localhost. v1
    assumes a trusted caller; the runner's `_validate_request` is the
    last-line defence (image allow-list, argv bounds, resource format).
    """

    image: str = Field(..., max_length=200, description="One of the allow-listed images.")
    script: str = Field(..., min_length=1, max_length=200_000)
    interpreter: list[str] | None = Field(
        None,
        max_length=8,
        description="Argv for the interpreter. Default: ['sh']. Use ['python'] for Python, etc.",
    )
    timeout_s: int = Field(60, ge=1, le=600)
    memory: str = Field("512m", pattern=r"^\d+(\.\d+)?[kmgtKMGT]?$")
    cpus: str = Field("1", pattern=r"^\d+(\.\d+)?[kmgtKMGT]?$")


class SandboxRunResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


@router.post("/run", response_model=SandboxRunResponse)
async def run(body: SandboxRunRequest) -> SandboxRunResponse:
    if not await docker_available():
        raise HTTPException(
            status_code=503,
            detail="Docker is not reachable from the API container/host; sandbox unavailable.",
        )
    req = SandboxRequest(
        image=body.image,
        script=body.script,
        interpreter=body.interpreter,
        timeout_s=body.timeout_s,
        memory=body.memory,
        cpus=body.cpus,
    )
    try:
        result = await sandbox_run(req)
    except SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SandboxRunResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_s=result.duration_s,
        timed_out=result.timed_out,
    )
