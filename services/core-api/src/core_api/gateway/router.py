"""Edge middleware: strip forged headers, then rate limit.

Order matters and is not arbitrary. Header stripping runs before anything reads a header,
so no later component can be fooled by a client-supplied `X-Sarana-*`. Rate limiting runs
after authentication, because the allowance depends on who is calling and an anonymous
limit applied to an authenticated operator would throttle the console.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core_api.gateway.proxy import SARANA_HEADER_PREFIX
from core_api.gateway.ratelimit import RateLimiter, bucket_key, limit_for

_log = structlog.get_logger(__name__)

RATE_LIMIT_HEADER: Final = "X-RateLimit-Limit"
RATE_REMAINING_HEADER: Final = "X-RateLimit-Remaining"

# Liveness and readiness must answer even when a caller is over its limit; a probe that
# gets a 429 looks like a dead container and gets the container killed.
_UNLIMITED_PATHS: Final = frozenset({"/healthz", "/readyz", "/metrics"})


class StripClientHeadersMiddleware(BaseHTTPMiddleware):
    """Remove every `X-Sarana-*` header a client sent.

    These headers are minted by the gateway and carry identity. A client that sets one is
    attempting to forge a principal, and the only safe response is for the header never to
    exist by the time authentication looks for one.

    Starlette exposes raw headers as a list of byte tuples on the scope; rewriting that
    list is what makes the change invisible to everything downstream, including any
    middleware that reads `request.headers` later.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        raw: list[tuple[bytes, bytes]] = request.scope.get("headers", [])
        kept = [
            (name, value)
            for name, value in raw
            if not name.decode("latin-1").lower().startswith(SARANA_HEADER_PREFIX)
        ]

        if len(kept) != len(raw):
            _log.info(
                "client_headers_stripped",
                path=request.url.path,
                removed=len(raw) - len(kept),
            )
            request.scope["headers"] = kept

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-principal rate limiting, returning 429 with Retry-After."""

    def __init__(self, app: object, *, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]  # Starlette's own annotation
        self.limiter = limiter or RateLimiter()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _UNLIMITED_PATHS:
            return await call_next(request)

        principal = getattr(request.state, "principal", None)
        client_ip = request.client.host if request.client else None
        key = bucket_key(principal, client_ip)
        decision = self.limiter.check(key, limit_for(principal))

        if not decision.allowed:
            _log.info(
                "rate_limited",
                path=request.url.path,
                limit=decision.limit,
                subject=getattr(principal, "subject_id", None),
            )
            response: Response = JSONResponse(
                status_code=429,
                content={
                    "type": "https://sarana.lk/errors/rate-limited",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": (
                        f"This caller is limited to {decision.limit} requests per minute. "
                        f"Retry in {decision.retry_after}s."
                    ),
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )
            response.headers["Retry-After"] = str(decision.retry_after)
        else:
            response = await call_next(request)

        response.headers[RATE_LIMIT_HEADER] = str(decision.limit)
        response.headers[RATE_REMAINING_HEADER] = str(decision.remaining)
        return response
