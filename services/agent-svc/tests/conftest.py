"""Test configuration for agent-svc."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agent_svc.config import Settings
from agent_svc.main import build_app
from sarana_shared.testing.fixtures import *  # noqa: F403 - shared fixtures by design


@pytest.fixture
def settings(postgres_url: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Settings pointing at the test container, with tracing off."""
    keys = tmp_path_factory.mktemp("keys")
    public_key = keys / "jwt-public.pem"
    public_key.write_text("", encoding="utf-8")
    return Settings(
        database_url=postgres_url,
        jwt_public_key_path=public_key,
        tracing_enabled=False,
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An httpx client wired straight to the ASGI app - no live server, no port."""
    app = build_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://agent-svc"
    ) as async_client:
        yield async_client
