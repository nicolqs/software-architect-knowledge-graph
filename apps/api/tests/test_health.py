"""Smoke test for the /health endpoint.

This test doesn't require live Neo4j/Postgres — it just asserts the route
is registered. The endpoint itself catches connection errors and reports
`degraded` rather than crashing, so a missing backend still returns 200.
A real integration test lands in M1's follow-up using testcontainers.
"""

from architect.main import create_app


def test_health_route_registered() -> None:
    app = create_app()
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/health" in routes
