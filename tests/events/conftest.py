"""Fixtures for the event backbone suite.

The outbox and idempotency guarantees are properties of transactions, so these run
against the real database. A mocked session commits nothing and rolls back nothing, which
is precisely what these tests are about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core_api.repo import OutboxEvent  # noqa: F401 - the representative outbox table
from sarana_shared.db.session import create_session_factory
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from tests.schema.conftest import (  # noqa: F401 - re-exported as fixtures
    db,
    migrated_url,
    schema_engine,
)

TEST_GROUP = "test-consumer"


@pytest_asyncio.fixture(loop_scope="session")
async def session_factory(schema_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions that really commit, because that is what is under test."""
    return create_session_factory(schema_engine)


@pytest_asyncio.fixture(loop_scope="session")
async def clean_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Empty the outbox and idempotency tables around each test.

    These tests commit for real, so they cannot rely on a transaction rollback to isolate
    themselves the way the schema suite does.
    """
    from sqlalchemy import text

    async def wipe() -> None:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM outbox.core_api_event"))
            await session.execute(text("DELETE FROM outbox.processed_event"))
            await session.execute(text("DELETE FROM outbox.dead_letter"))
            await session.commit()

    await wipe()
    yield
    await wipe()


@pytest.fixture
def bus() -> InMemoryEventBus:
    """An in-process bus that records everything, including refused replays."""
    return InMemoryEventBus()
