"""Cross-cutting HTTP middleware every service mounts.

Correlation propagation is the important one: the ID arrives on a header, binds to the
request context, reaches every log line and every event published during the request,
and goes back out on the response so a caller can quote it in a support ticket.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Final

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from sarana_shared.domain.ids import (
    new_correlation_id,
    parse_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)

CORRELATION_HEADER: Final = "X-Correlation-Id"

# Probes are logged at debug only; at one probe per second per replica they would
# otherwise dominate the log volume during the quiet years between disasters.
PROBE_PATHS: Final[frozenset[str]] = frozenset({"/healthz", "/readyz", "/metrics"})

_log = structlog.get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Bind a correlation ID for the lifetime of the request.

    An inbound `X-Correlation-Id` is honoured so the chain survives a hop between
    services; otherwise a new one is minted here.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # An inbound ID is honoured only if it is a UUID. Forwarding arbitrary header
        # text would put a caller's choice of string into every log line, every event
        # payload and every audit entry the request produces.
        incoming = parse_correlation_id(request.headers.get(CORRELATION_HEADER))
        correlation_id = incoming or new_correlation_id()

        set_correlation_id(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
            reset_correlation_id()

        response.headers[CORRELATION_HEADER] = correlation_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request. Never logs query strings or bodies.

    Query strings are excluded deliberately: `?phone=07...` in a URL is exactly the kind
    of accidental disclosure the redaction deny-list exists to prevent, and a URL is the
    easiest place for one to appear.
    """

    def __init__(self, app: ASGIApp, *, service: str) -> None:
        super().__init__(app)
        self._service = service

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

        log = _log.bind(
            service=self._service,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=elapsed_ms,
        )
        if request.url.path in PROBE_PATHS:
            log.debug("probe")
        elif response.status_code >= 500:
            log.error("request_completed")
        else:
            log.info("request_completed")

        return response
