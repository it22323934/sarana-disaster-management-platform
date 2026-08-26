"""See services/core-api/tests/conftest.py for why the env var is set before import
rather than passed around a bypassed Settings object.
"""

import os
from collections.abc import AsyncIterator

os.environ.setdefault(
    "SARANA_GOV_MOCK_DATABASE_URL",
    "postgresql+asyncpg://sarana_app:sarana_app@localhost:5432/sarana",
)

import pytest_asyncio
from gov_mock.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
