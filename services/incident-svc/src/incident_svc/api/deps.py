"""Request-scoped dependencies for incident-svc.

The session dependency applies the caller's administrative scope to the connection, so
row-level security is in force for the whole request. Doing it here rather than per
handler means a new endpoint is scoped by default and forgetting fails closed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from incident_svc.config import Settings
from sarana_shared.auth.middleware import apply_row_security_scope
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


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
CorrelationDep = Annotated[str, Depends(get_correlation_id)]
