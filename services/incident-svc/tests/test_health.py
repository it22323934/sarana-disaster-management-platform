from httpx import AsyncClient


async def test_healthz_is_always_up(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "incident-svc"}


async def test_readyz_degrades_gracefully_without_a_database(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is False
    assert body["status"] == "degraded"
