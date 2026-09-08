"""Request-scoped dependencies for ledger-svc.

The session dependency applies the caller's administrative scope to the connection, so
row-level security is in force for the whole request. Doing it here rather than per
handler means a new endpoint is scoped by default and forgetting fails closed - which
matters more in this service than any other, because the rows are people's money.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger_svc.config import Settings
from sarana_shared.auth.middleware import apply_row_security_scope, mark_public_aggregate_read
from sarana_shared.auth.principal import Principal
from sarana_shared.errors import Unauthenticated


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_principal(request: Request) -> Principal:
    """The authenticated principal, or refuse."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise Unauthenticated(
            "Authentication required.", context={"reason": "no_principal_on_request"}
        )
    return principal  # type: ignore[no-any-return]  # set by AuthenticationMiddleware


def get_correlation_id(request: Request) -> str:
    """The correlation id for this request, however it arrived."""
    existing = getattr(request.state, "correlation_id", None)
    return str(existing) if existing else str(request.headers.get("x-correlation-id", ""))


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transactional session with row-level security scoped to the caller."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    principal = getattr(request.state, "principal", None)

    async with factory() as session:
        connection = await session.connection()
        await apply_row_security_scope(connection, principal)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_public_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session for the unauthenticated public endpoints.

    There is no principal to scope by, so `apply_row_security_scope` is called with None
    and the connection gets the empty scope. The public queries then select only from the
    aggregated, anonymised projections - the scope is a second fence, not the first.

    The second call is what makes the first sentence workable. An empty scope covers
    nothing, and `aid.damage_assessment` is under FORCE row-level security, so every
    public query that joins it - the district summary since file 10, and the funnel and
    district metrics since file 21 - was silently filtered to zero rows. It looked like a
    country that had disbursed nothing, which is indistinguishable from a correct empty
    database. `mark_public_aggregate_read` sets the transaction-local marker that
    ledger-svc migration 0011's SELECT-only policy tests for; see that migration for why
    it is a second permissive policy rather than a weaker first one.

    Read-only by construction: this dependency never commits, so a handler that tried to
    write through it would roll back at the end of the request.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory

    async with factory() as session:
        connection = await session.connection()
        await apply_row_security_scope(connection, None)
        await mark_public_aggregate_read(connection)
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PublicSessionDep = Annotated[AsyncSession, Depends(get_public_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
CorrelationDep = Annotated[str, Depends(get_correlation_id)]
