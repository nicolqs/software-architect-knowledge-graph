"""Eval cases load and have the expected shape."""

from architect.evals.runner import CASES_DIR, _load_cases


def test_cases_dir_exists() -> None:
    assert CASES_DIR.is_dir(), f"missing cases dir: {CASES_DIR}"


def test_smoke_case_present() -> None:
    cases = _load_cases()
    by_name = {c["name"]: c for c in cases}
    assert "echo-builds" in by_name
    assert by_name["echo-builds"]["kind"] == "smoke"


def test_agent_case_has_assertions() -> None:
    cases = _load_cases()
    by_name = {c["name"]: c for c in cases}
    greets = by_name.get("echo-greets")
    assert greets is not None
    assert greets["kind"] == "agent"
    assert greets["assertions"], "agent case must declare at least one assertion"
