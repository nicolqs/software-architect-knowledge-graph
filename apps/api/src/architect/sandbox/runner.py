"""Docker-backed sandbox runner.

What this is used for: agents (Architect, Refactor) need to *validate*
their proposals — e.g. run a DB migration script against ephemeral
infrastructure, or dry-run a generated codemod against a target file.
That code is untrusted by design; we don't run it on the host.

Hardening (per the plan's M5 spec):
- `--network=none`       no internet, no host-network access.
- `--read-only`          rootfs is RO; per-run tmpfs at /tmp.
- `--cap-drop=ALL`       drop every linux capability.
- `--user 65534:65534`   `nobody:nogroup`, rootless.
- `--pids-limit 128`
- `--cpus 1`
- `--memory 512m`
- Wall-clock timeout enforced by the orchestrator, not just Docker.
- Image name allow-listed — agents can't request `:latest` of arbitrary
  registries. The list is in `_ALLOWED_IMAGES`.

We pass the script body via stdin to the container's interpreter — no
host bind mount needed, which avoids the uid-mismatch permission issues
that plague rootless container + host-tmpdir setups.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

# Images we trust enough to run with the above flags. Add to this list
# *deliberately*; never let the request body pick an arbitrary image.
_ALLOWED_IMAGES: frozenset[str] = frozenset(
    {
        "python:3.12-slim",
        "node:20-alpine",
        "postgres:16-alpine",
        "alpine:3.20",
    }
)

_DEFAULT_TIMEOUT_S = 60
_DEFAULT_MEMORY = "512m"
_DEFAULT_CPUS = "1"
_DEFAULT_PIDS = 128


class SandboxError(RuntimeError):
    pass


@dataclass(slots=True)
class SandboxRequest:
    image: str
    script: str
    interpreter: list[str] | None = None  # default depends on image (see _interpreter_for)
    timeout_s: int = _DEFAULT_TIMEOUT_S
    memory: str = _DEFAULT_MEMORY
    cpus: str = _DEFAULT_CPUS


@dataclass(slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


_MAX_INTERPRETER_ARGS = 8
_MAX_INTERPRETER_ARG_LEN = 200
# Docker accepts e.g. "512m", "2g", "1024"; refuse anything else.
_RESOURCE_RE = re.compile(r"^\d+(\.\d+)?[kmgtKMGT]?$")


def _validate_request(req: SandboxRequest) -> None:
    if req.image not in _ALLOWED_IMAGES:
        raise SandboxError(
            f"Image {req.image!r} is not in the sandbox allow-list. "
            f"Allowed: {sorted(_ALLOWED_IMAGES)}"
        )
    if req.timeout_s < 1 or req.timeout_s > 600:
        raise SandboxError("timeout_s must be between 1 and 600")
    if len(req.script) > 200_000:
        raise SandboxError("script must be <= 200kB")
    if req.interpreter is not None:
        if len(req.interpreter) > _MAX_INTERPRETER_ARGS:
            raise SandboxError(
                f"interpreter accepts at most {_MAX_INTERPRETER_ARGS} args; got {len(req.interpreter)}"
            )
        for arg in req.interpreter:
            if not isinstance(arg, str) or len(arg) > _MAX_INTERPRETER_ARG_LEN:
                raise SandboxError(
                    f"interpreter arg must be a string ≤{_MAX_INTERPRETER_ARG_LEN} chars"
                )
    if not _RESOURCE_RE.match(req.memory):
        raise SandboxError(f"memory must be like '512m' or '2g'; got {req.memory!r}")
    if not _RESOURCE_RE.match(req.cpus):
        raise SandboxError(f"cpus must be a number like '1' or '0.5'; got {req.cpus!r}")


def _interpreter_for(req: SandboxRequest) -> list[str]:
    if req.interpreter:
        return req.interpreter
    if req.image.startswith("python:"):
        return ["python", "-"]  # python reads stdin when `-` given
    if req.image.startswith("node:"):
        return ["node", "-"]
    return ["sh"]


async def run(req: SandboxRequest) -> SandboxResult:
    """Run a script inside a hardened ephemeral container.

    The script body is piped via stdin to the interpreter — no host bind
    mount needed (avoids uid-mismatch under rootless containers).

    On timeout we explicitly `docker kill <name>` rather than relying on
    Docker's broken-`-i`-connection auto-cleanup, which is timing-sensitive
    and can leave a container running for seconds after the deadline.
    """
    _validate_request(req)
    interpreter = _interpreter_for(req)
    container_name = f"architect-sbx-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",                       # keep stdin open so we can pipe the script
        "--name", container_name,
        "--network=none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        f"--memory={req.memory}",
        f"--cpus={req.cpus}",
        f"--pids-limit={_DEFAULT_PIDS}",
        "--cap-drop=ALL",
        "--user", "65534:65534",
        "--entrypoint", interpreter[0],
        req.image,
        *interpreter[1:],
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    start = asyncio.get_event_loop().time()
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=req.script.encode("utf-8")),
            timeout=req.timeout_s,
        )
    except TimeoutError:
        timed_out = True
        # Kill the container itself, not just the docker CLI. The CLI might
        # auto-clean, but explicit kill closes the race window.
        await _docker_kill(container_name)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        try:
            stdout_b, stderr_b = await proc.communicate()
        except (BrokenPipeError, OSError):
            stdout_b, stderr_b = b"", b""
    duration = asyncio.get_event_loop().time() - start

    return SandboxResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        duration_s=round(duration, 3),
        timed_out=timed_out,
    )


async def _docker_kill(container_name: str) -> None:
    """Best-effort `docker kill <name>`. Swallows all errors — the container
    may already be gone (the CLI auto-cleaned), in which case kill exits 1
    and that's fine."""
    with contextlib.suppress(Exception):
        proc = await asyncio.create_subprocess_exec(
            "docker", "kill", container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)


async def docker_available() -> bool:
    """Quick probe: is the docker CLI reachable and the daemon up?"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "version", "--format", "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=3)
        return proc.returncode == 0
    except (FileNotFoundError, TimeoutError):
        return False


__all__ = [
    "_ALLOWED_IMAGES",
    "SandboxError",
    "SandboxRequest",
    "SandboxResult",
    "docker_available",
    "run",
]
