from httpx import AsyncClient


async def test_healthz_is_always_up(client: AsyncClient) -> None:
    """Liveness must report ok regardless of the database, or the container gets killed
    into a restart loop the moment the DB has a blip (docs/build-prompts/07-core-api.md)."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "core-api"}


async def test_readyz_degrades_gracefully_without_a_database(client: AsyncClient) -> None:
    """No Postgres is running in this test — readyz must report "degraded", not crash."""
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is False
    assert body["status"] == "degraded"
