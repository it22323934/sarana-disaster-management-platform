"""Request-scoped dependencies for core-api.

The database session dependency does one thing beyond opening a transaction: it applies
the principal's administrative scope to the connection, so row-level security is in force
for the whole request. Doing it here rather than in each handler means a new endpoint is
scoped by default, and forgetting fails closed - an unset scope covers nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core_api.config import Settings
from core_api.domain.auth.password import PasswordHasherService
from sarana_shared.auth.middleware import apply_row_security_scope
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.tokens import TokenService
from sarana_shared.crypto.keyed import FieldCipher, KeyedHasher
from sarana_shared.errors import Unauthenticated


def get_settings(request: Request) -> Settings:
    """The settings this app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_tokens(request: Request) -> TokenService:
    """The token service. core-api is the only issuer."""
    service: TokenService = request.app.state.tokens
    return service


def get_password_hasher(request: Request) -> PasswordHasherService:
    """The Argon2id hasher, built once at startup."""
    hasher: PasswordHasherService = request.app.state.password_hasher
    return hasher


def get_keyed_hasher(request: Request) -> KeyedHasher:
    """Deterministic HMAC for lookup keys."""
    hasher: KeyedHasher = request.app.state.keyed_hasher
    return hasher


def get_field_cipher(request: Request) -> FieldCipher:
    """Field-level encryption for recoverable personal data."""
    cipher: FieldCipher = request.app.state.field_cipher
    return cipher


def get_principal(request: Request) -> Principal:
    """The authenticated principal, or refuse.

    Endpoints that need a specific permission depend on `require(...)` instead; this is
    for the handful that need only to know who is calling.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise Unauthenticated(
            "Authentication required.", context={"reason": "no_principal_on_request"}
        )
    return principal  # type: ignore[no-any-return]  # set by AuthenticationMiddleware


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transactional session with row-level security scoped to the caller.

    Commits on success, rolls back on any exception. The scope is applied inside the
    transaction with SET LOCAL, so it dies with the transaction and cannot leak to
    whichever request borrows this pooled connection next.
    """
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
TokensDep = Annotated[TokenService, Depends(get_tokens)]
PasswordDep = Annotated[PasswordHasherService, Depends(get_password_hasher)]
KeyedHasherDep = Annotated[KeyedHasher, Depends(get_keyed_hasher)]
FieldCipherDep = Annotated[FieldCipher, Depends(get_field_cipher)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
