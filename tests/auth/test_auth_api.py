"""The authentication HTTP surface, exercised end to end against a real database.

These go through the actual app: middleware, dependencies, row-level security scoping and
the routers. A unit test of the domain layer proves the rule is right; this proves the
rule is reachable and that nothing in the wiring quietly bypasses it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from core_api.config import Settings
from core_api.domain.auth.password import PasswordHasherService
from core_api.main import build_app
from sarana_shared.domain.ids import uuid7
from tests.schema.conftest import REPO_ROOT

pytestmark = pytest.mark.asyncio(loop_scope="session")

HMAC_KEY = "11" * 32
CIPHER_KEY = "22" * 32
PASSWORD = "a-long-enough-passphrase"


@pytest.fixture(scope="session")
def api_settings(migrated_url: str) -> Settings:
    """Settings pointing at the migrated test database, tracing off."""
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return Settings(
        database_url=migrated_url,
        jwt_public_key_path=keys / "jwt-public.pem",
        jwt_private_key_path=keys / "jwt-private.pem",
        pii_hmac_key=HMAC_KEY,
        pii_cipher_key=CIPHER_KEY,
        tracing_enabled=False,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def client(api_settings: Settings) -> AsyncIterator[AsyncClient]:
    """An httpx client wired straight to the ASGI app, lifespan and all."""
    app = build_app(api_settings)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://core-api") as async_client,
    ):
        yield async_client


async def _make_officer(db: AsyncConnection, email: str) -> str:
    """Create an ACTIVE account with a known password. Returns its id."""
    user_id = uuid7()
    hasher = PasswordHasherService.create()
    await db.execute(
        text(
            "INSERT INTO admin.app_user (id, email, password_hash, full_name, status) "
            "VALUES (:id, :email, :hash, 'Test Officer', 'ACTIVE')"
        ),
        {"id": user_id, "email": email, "hash": hasher.hash(PASSWORD)},
    )
    await db.commit()
    return str(user_id)


async def test_the_jwks_endpoint_publishes_the_signing_key(client: AsyncClient) -> None:
    """Every other service verifies against this rather than calling core-api."""
    response = await client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    document = response.json()
    assert document["keys"][0]["alg"] == "RS256"
    assert document["keys"][0]["use"] == "sig"
    assert "d" not in document["keys"][0], "the private exponent must never be published"


async def test_the_jwks_endpoint_is_anonymous(client: AsyncClient) -> None:
    """There is nothing secret in it, and local verification depends on reaching it."""
    response = await client.get("/.well-known/jwks.json")

    assert response.status_code == 200


async def test_a_protected_endpoint_refuses_an_anonymous_caller(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/auth/step-up", json={"code": "123456"})

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_a_garbage_token_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/step-up",
        json={"code": "123456"},
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401
