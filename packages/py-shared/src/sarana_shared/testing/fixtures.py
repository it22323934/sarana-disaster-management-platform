"""The four fixtures docs/build-prompts/03-monorepo-scaffold.md asks for: db, client,
event bus, frozen clock. Each service's own conftest.py re-exports what it needs from
here rather than redefining them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from sarana_shared.db.base import Base
from sarana_shared.db.session import make_engine, make_session_factory
from sarana_shared.events.impl.in_memory import InMemoryEventBus

# A PostGIS+pgvector image, not plain postgres — per 02-conventions.md, PostGIS/pgvector
# behaviour is exactly what must not be mocked away.
_POSTGIS_IMAGE = "ghcr.io/baosystems/postgis:16-3.4"

_EXTENSIONS_SQL = text(
    'CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS "vector";'
)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(_POSTGIS_IMAGE, driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def postgres_engine(postgres_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(postgres_container.get_connection_url())
    async with engine.begin() as conn:
        await conn.execute(_EXTENSIONS_SQL)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def postgres_session(postgres_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = make_session_factory(postgres_engine)
    async with session_factory() as session:
        yield session
        await session.rollback()  # every test starts from a clean slate


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@contextmanager
def _patched_now_utc(frozen_at: datetime) -> Iterator[None]:
    with patch("sarana_shared.domain.time.now_utc", return_value=frozen_at):
        yield


@pytest.fixture
def frozen_clock() -> Iterator[datetime]:
    """Freezes sarana_shared.domain.time.now_utc() to a fixed instant for the duration
    of the test. Import `now_utc` from sarana_shared.domain.time in application code
    (never `datetime.now()` directly) so this fixture actually takes effect."""
    frozen_at = datetime(2026, 9, 1, 6, 0, 0, tzinfo=UTC)
    with _patched_now_utc(frozen_at):
        yield frozen_at
