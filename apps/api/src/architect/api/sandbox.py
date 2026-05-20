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
    image: str = Field(..., description="One of the allow-listed images (see sandbox.runner).")
    script: str = Field(..., description="Script body to execute.", min_length=1, max_length=200_000)
    interpreter: list[str] | None = Field(
        None,
        description="Argv for the interpreter. Default: ['sh']. Use ['python'] for Python, etc.",
    )
    timeout_s: int = Field(60, ge=1, le=600)
    memory: str = Field("512m")
    cpus: str = Field("1")


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
