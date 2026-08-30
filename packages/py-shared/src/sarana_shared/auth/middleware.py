"""Authentication middleware: builds the principal and hands the database its scope.

Two jobs, and the second is the one that matters most.

It verifies the bearer token locally against the cached JWKS and puts a `Principal` on
the request. No call to core-api: a synchronous dependency on one service in the path of
every authorised request would be a single point of failure during exactly the event this
platform exists for.

Then it makes the principal's areas available to PostgreSQL as `sarana.user_scope`, which
is what the row-level security policies read. Application checks are the first line; RLS
is the one that holds when a handler forgets its filter. That only works if the scope
actually reaches the session, which is this middleware's responsibility and nothing
else's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from sarana_shared.auth.principal import Principal
from sarana_shared.auth.tokens import TokenKind, TokenService, bearer_token
from sarana_shared.db.sql import SCOPE_SETTING
from sarana_shared.errors import SaranaError, problem_response

_log = structlog.get_logger(__name__)

# Paths served without a credential. Everything else needs one.
ANONYMOUS_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/.well-known/jwks.json",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        # The client-credentials grant. Anonymous for the same reason /login is: it is
        # where a caller *becomes* authenticated, and requiring a token to obtain a token
        # is a bootstrap nobody can complete. The credential is in the body and the
        # endpoint refuses everything that does not match it.
        "/api/v1/auth/token",
        # Enum labels, not data about anyone. The sign-in screen needs its own language
        # picker before there is a token to present, so requiring one here would mean a
        # citizen could not read the page that asks them to log in.
        "/api/v1/meta/reference",
        # The transparency surface, at the paths build file 10 names. Anonymous is the
        # whole point: a journalist checking these figures against the S3 anchors must not
        # need an account from the institution whose numbers they are checking. Each is
        # aggregated to district and day in SQL - see `ledger_svc.repo.queries`.
        "/api/v1/ledger/public",
        "/api/v1/ledger/anchors",
        # The compensating entries. Published on the same terms: a feed showing only the
        # payments that succeeded is not a transparency surface.
        "/api/v1/ledger/reversals",
        "/api/v1/cost-schedules",
    }
)

# Prefixes open to anyone. The public transparency dashboard reads aggregate figures with
# no account at all - that is the point of it.
ANONYMOUS_PREFIXES: Final[tuple[str, ...]] = ("/api/v1/public/",)


def is_anonymous_path(path: str) -> bool:
    """Whether this path is served without a credential."""
    return path in ANONYMOUS_PATHS or path.startswith(ANONYMOUS_PREFIXES)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Verifies the bearer token and attaches the principal to the request.

    A missing or bad token on a protected path is refused here rather than in each
    handler, so a new endpoint is authenticated by default. Authorisation - which scope,
    which area - stays with the endpoint, because only the endpoint knows what it does.
    """

    def __init__(self, app: ASGIApp, *, tokens: TokenService) -> None:
        super().__init__(app)
        self._tokens = tokens

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if is_anonymous_path(request.url.path):
            request.state.principal = None
            return await call_next(request)

        try:
            credential = bearer_token(request.headers.get("Authorization"))
            # A capability token is a different kind, so it is verified as one. Accepting
            # it wherever an access token is expected would undo the point of the kind.
            claims = self._tokens.verify(credential, expect=_expected_kind(request))
            principal = claims.to_principal()
        except SaranaError as exc:
            # Rendered here rather than raised: middleware sits above the app's exception
            # handlers, so raising would surface as an unhandled 500 and every failed
            # authentication would look like a server fault.
            _log.info(
                "authentication_failed",
                path=request.url.path,
                reason=exc.context.get("reason"),
            )
            return problem_response(exc.to_problem(instance=request.url.path))

        request.state.principal = principal
        structlog.contextvars.bind_contextvars(subject_id=principal.subject_id)
        try:
            return await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("subject_id")


def _expected_kind(request: Request) -> TokenKind:
    """Which token kind this path accepts.

    Only the assessment draft endpoint accepts a capability token, and it accepts either.
    The header names the kind so a stale capability token on a reconnected device gets a
    clear refusal rather than a confusing scope error.
    """
    if request.headers.get("X-Sarana-Token-Kind") == "capability":
        return "capability"
    return "access"


async def apply_row_security_scope(
    connection: AsyncConnection, principal: Principal | None
) -> None:
    """Set `sarana.user_scope` for the current transaction.

    SET LOCAL, not SET: the value dies with the transaction, so it cannot leak to the
    next request that borrows this pooled connection. An unset scope covers nothing, so
    forgetting to call this fails closed - the handler sees no rows rather than all of
    them.
    """
    codes = ",".join(sorted(principal.area_codes)) if principal else ""
    # The value is built from the token's own grants, which were validated on parse, so
    # it cannot carry anything a caller chose. Quoting it anyway costs nothing.
    await connection.execute(
        text(f"SELECT set_config('{SCOPE_SETTING}', :scope, true)"), {"scope": codes}
    )
