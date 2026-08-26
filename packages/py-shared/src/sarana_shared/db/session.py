"""Async engine + session factory. Every service builds its own engine from its own
`SARANA_{SERVICE}_DATABASE_URL`, but through this one constructor, so pool sizing,
statement timeout, and RLS session-variable wiring stay consistent across all six.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(
    database_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 5,
    statement_timeout_ms: int = 10_000,
) -> AsyncEngine:
    """A pool that fails fast rather than queuing forever — a hung request during a
    disaster surge is worse than a fast, visible 503 (docs/build-prompts/07-core-api.md)."""
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={"server_settings": {"statement_timeout": str(statement_timeout_ms)}},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_scope: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """One request, one transaction. `user_scope`, when given, sets
    `sarana.user_scope` for the request via `SET LOCAL` so Postgres row-level security
    (docs/build-prompts/04-data-model.md) is the backstop behind the application-level
    RBAC check, not a second copy of it.
    """
    async with session_factory() as session, session.begin():
        if user_scope is not None:
            # SET LOCAL cannot be parameterised as a bind param. user_scope must already
            # be a server-generated principal id validated by auth/tokens.py — never raw
            # client input — by the time it reaches here.
            if not user_scope.replace("-", "").isalnum():
                raise ValueError(
                    f"Refusing to interpolate an unexpected user_scope: {user_scope!r}"
                )
            await session.execute(text(f"SET LOCAL sarana.user_scope = '{user_scope}'"))
        yield session
