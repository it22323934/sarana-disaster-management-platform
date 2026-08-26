"""main.py's module-level `app = create_app()` deliberately reads required settings from
the environment at import time — "fail loudly at boot", not a KeyError at request time
(docs/build-prompts/03-monorepo-scaffold.md). So this conftest sets that environment
*before* core_api.main is ever imported, rather than bypassing config loading — the same
path a real deployment takes, just pointed at a throwaway URL tests don't actually need
to connect to (readyz's database check fails closed to "degraded" instead of raising).
"""

import os
from collections.abc import AsyncIterator

os.environ.setdefault(
    "SARANA_CORE_API_DATABASE_URL",
    "postgresql+asyncpg://sarana_app:sarana_app@localhost:5432/sarana",
)

import pytest_asyncio
from core_api.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
