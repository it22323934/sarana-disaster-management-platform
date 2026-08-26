"""The operational endpoints agent-svc must always expose."""

from __future__ import annotations

from httpx import AsyncClient


async def test_healthz_reports_the_service_and_version(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "agent-svc"
    assert body["version"]


async def test_healthz_does_not_touch_dependencies(client: AsyncClient) -> None:
    """Liveness must stay green when a dependency is down.

    A database blip must remove the replica from the load balancer, not cause the
    orchestrator to kill and restart an otherwise healthy process.
    """
    response = await client.get("/healthz")

    assert response.status_code == 200


async def test_readyz_names_every_dependency(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code in (200, 503)
    body = response.json()
    assert body["service"] == "agent-svc"
    assert set(body["checks"]) == {"database", "event_bus"}


async def test_metrics_are_exposed_in_prometheus_format(client: AsyncClient) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


async def test_correlation_id_is_echoed_back(client: AsyncClient) -> None:
    """An inbound correlation ID survives the request so a caller can quote it."""
    response = await client.get("/healthz", headers={"X-Correlation-Id": "chain-123"})

    assert response.headers["X-Correlation-Id"] == "chain-123"


async def test_unknown_route_returns_problem_details(client: AsyncClient) -> None:
    """Never a bare string, not even for a routing miss."""
    response = await client.get("/no-such-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["correlation_id"]
