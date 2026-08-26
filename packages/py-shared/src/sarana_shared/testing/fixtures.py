"""Shared pytest fixtures.

Conventions: Testcontainers for Postgres, never a mocked database. PostGIS and pgvector
behaviour is the thing most likely to be wrong, and a mock proves nothing about either.

A service's `conftest.py` re-exports what it needs:

    from sarana_shared.testing.fixtures import *  # noqa: F403
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sarana_shared.db.base import Base
from sarana_shared.db.session import (
    DatabaseSettings,
    create_engine,
    create_session_factory,
)
from sarana_shared.domain.ids import reset_correlation_id, set_correlation_id
from sarana_shared.events.bus import InMemoryEventBus

# The compose stack builds this image; tests reuse it so the extensions match production.
POSTGRES_IMAGE = os.environ.get("SARANA_TEST_POSTGRES_IMAGE", "sarana/postgres:16-3.4-pgvector")

# Schemas every service expects to exist. Created once per test database.
SERVICE_SCHEMAS: tuple[str, ...] = (
    "platform",
    "reference",
    "resilience",
    "incident",
    "alerting",
    "ledger",
    "agent",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the `--live-llm` flag.

    Agent tests run against recorded fixtures by default. This flag opts a run into
    hitting the real OpenAI API, which costs money and is not deterministic.
    """
    parser.addoption(
        "--live-llm",
        action="store_true",
        default=False,
        help="Run agent tests against the live OpenAI API instead of recorded fixtures.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `live_llm`-marked tests unless `--live-llm` was passed."""
    if config.getoption("--live-llm"):
        return
    skip = pytest.mark.skip(reason="needs --live-llm")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a PostGIS + pgvector container for the session and yield its async DSN.

    Set `SARANA_TEST_DATABASE_URL` to point at an already-running database and skip the
    container entirely - useful in CI where a service container is already up.
    """
    existing = os.environ.get("SARANA_TEST_DATABASE_URL")
    if existing:
        yield existing
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    """A session-scoped engine with extensions and schemas already installed."""
    from sqlalchemy import text

    engine = create_engine(DatabaseSettings(url=postgres_url, application_name="sarana-tests"))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        for schema in SERVICE_SCHEMAS:
            await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await connection.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the test engine."""
    return create_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test.

    Every test sees a clean database without paying to recreate the schema, and no test
    can leak state into the next one.
    """
    async with session_factory() as session:
        transaction = await session.begin()
        try:
            yield session
        finally:
            await transaction.rollback()


@pytest.fixture
def event_bus() -> Iterator[InMemoryEventBus]:
    """An in-process event bus that records everything published."""
    bus = InMemoryEventBus()
    yield bus
    bus.clear()


@pytest.fixture(autouse=True)
def correlation() -> Iterator[str]:
    """Bind a fixed correlation ID for the test and clear it afterwards.

    Autouse, so an assertion on a log line or an event envelope has a stable value to
    compare against rather than a fresh UUID per call.
    """
    value = "test-correlation-0000"
    set_correlation_id(value)
    yield value
    reset_correlation_id()


class FrozenClock:
    """A controllable clock for tests that assert on disaster-relative timing."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware start instant")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        """The current frozen instant."""
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward and return the new instant."""
        self._now += delta
        return self._now

    def set(self, moment: datetime) -> datetime:
        """Jump the clock to an absolute instant."""
        self._now = moment.astimezone(UTC)
        return self._now


# Cyclone Ditwah landfall on Sri Lanka's east coast, 28 Nov 2025, 00:00 Colombo.
# Every scenario fixture is expressed relative to this instant.
DITWAH_LANDFALL = datetime(2025, 11, 27, 18, 30, tzinfo=UTC)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """A clock frozen at Ditwah landfall."""
    return FrozenClock(DITWAH_LANDFALL)


@pytest.fixture(scope="session")
def dev_keys_dir() -> Path:
    """Path to the local RS256 keypair generated by `make keys`."""
    root = Path(__file__).resolve().parents[4]
    return root / "infra" / "docker" / "dev-keys"


@pytest.fixture
def anyio_backend() -> str:
    """Pin anyio to asyncio - trio is not a supported runtime here."""
    return "asyncio"


def problem_of(response: Any) -> dict[str, Any]:
    """Assert a response is a Problem Details document and return it.

    Test helper rather than a fixture: every error-path assertion should go through it,
    so a handler that returns a bare string is caught by the first test that touches it.
    """
    assert response.headers["content-type"].startswith("application/problem+json"), (
        f"expected application/problem+json, got {response.headers.get('content-type')!r}"
    )
    body: dict[str, Any] = response.json()
    for required in ("type", "title", "status", "correlation_id"):
        assert required in body, f"Problem Details is missing {required!r}: {body}"
    return body
