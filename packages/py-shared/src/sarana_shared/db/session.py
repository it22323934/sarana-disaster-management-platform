"""Async engine and session factory.

One PostgreSQL, schema per service (ADR-002). All persistence goes through repository
classes; this module owns the connection lifecycle and nothing else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Ledger writes run SERIALIZABLE (ADR-001) - the isolation level a repository asks for
# explicitly, never a global default that would slow every read.
SERIALIZABLE = "SERIALIZABLE"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection tuning. Sourced from each service's settings object."""

    url: str
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 5
    pool_timeout_s: int = 30
    pool_recycle_s: int = 1_800
    statement_timeout_ms: int = 15_000
    application_name: str = "sarana"


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build the async engine for a service.

    `statement_timeout` is set per connection rather than per query: a runaway PostGIS
    query during a cyclone must not hold a pool slot indefinitely.
    """
    return create_async_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_s,
        pool_recycle=settings.pool_recycle_s,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": settings.application_name,
                "statement_timeout": str(settings.statement_timeout_ms),
                "timezone": "UTC",
            }
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory with expire_on_commit off.

    Objects stay usable after commit, which is what a FastAPI handler needs when it
    serialises a model it just wrote.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
    *,
    isolation_level: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """A transactional scope. Commits on success, rolls back on any exception.

    Pass `isolation_level=SERIALIZABLE` for ledger writes.
    """
    async with factory() as session:
        if isolation_level is not None:
            await session.connection(execution_options={"isolation_level": isolation_level})
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection(engine: AsyncEngine) -> bool:
    """Readiness probe: can we round-trip a trivial query?"""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - a probe reports false, it never propagates
        return False
    return True


async def dispose_engine(engine: AsyncEngine) -> None:
    """Close every pooled connection. Called from the FastAPI lifespan shutdown."""
    await engine.dispose()
