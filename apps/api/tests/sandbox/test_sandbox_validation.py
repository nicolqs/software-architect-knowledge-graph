"""Pure unit tests for the sandbox validation layer — no Docker needed."""

import pytest

from architect.sandbox.runner import (
    _ALLOWED_IMAGES,
    SandboxError,
    SandboxRequest,
    _validate_request,
)


def test_validate_rejects_unknown_image() -> None:
    req = SandboxRequest(image="malicious/image:latest", script="echo hi")
    with pytest.raises(SandboxError, match="allow-list"):
        _validate_request(req)


def test_validate_accepts_allow_listed_image() -> None:
    req = SandboxRequest(image=next(iter(_ALLOWED_IMAGES)), script="echo hi")
    # No raise.
    _validate_request(req)


def test_validate_rejects_timeout_out_of_range() -> None:
    img = next(iter(_ALLOWED_IMAGES))
    with pytest.raises(SandboxError, match="timeout_s"):
        _validate_request(SandboxRequest(image=img, script="echo", timeout_s=0))
    with pytest.raises(SandboxError, match="timeout_s"):
        _validate_request(SandboxRequest(image=img, script="echo", timeout_s=10_000))


def test_validate_rejects_huge_script() -> None:
    img = next(iter(_ALLOWED_IMAGES))
    huge = "x" * 200_001
    with pytest.raises(SandboxError, match="<= 200kB"):
        _validate_request(SandboxRequest(image=img, script=huge))


def test_allow_list_includes_expected_runtimes() -> None:
    # Smoke: the runtimes the architect/refactor flows need are present.
    assert "python:3.12-slim" in _ALLOWED_IMAGES
    assert "postgres:16-alpine" in _ALLOWED_IMAGES
