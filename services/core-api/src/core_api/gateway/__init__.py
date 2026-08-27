"""The edge: header hygiene, rate limits, circuit breakers and downstream forwarding."""

from __future__ import annotations

from core_api.gateway.breaker import (
    BreakerRegistry,
    BreakerState,
    CircuitBreaker,
    CircuitOpen,
)
from core_api.gateway.proxy import (
    CORRELATION_HEADER,
    PRINCIPAL_HEADER,
    SARANA_HEADER_PREFIX,
    Downstream,
    DownstreamUnavailable,
    InternalPrincipalMinter,
    ProxyResponse,
    ServiceProxy,
    strip_client_headers,
)
from core_api.gateway.ratelimit import (
    ANONYMOUS_LIMIT,
    CITIZEN_LIMIT,
    OFFICER_LIMIT,
    OPERATOR_LIMIT,
    Decision,
    RateLimiter,
    bucket_key,
    limit_for,
)
from core_api.gateway.router import RateLimitMiddleware, StripClientHeadersMiddleware

__all__ = [
    "ANONYMOUS_LIMIT",
    "CITIZEN_LIMIT",
    "CORRELATION_HEADER",
    "OFFICER_LIMIT",
    "OPERATOR_LIMIT",
    "PRINCIPAL_HEADER",
    "SARANA_HEADER_PREFIX",
    "BreakerRegistry",
    "BreakerState",
    "CircuitBreaker",
    "CircuitOpen",
    "Decision",
    "Downstream",
    "DownstreamUnavailable",
    "InternalPrincipalMinter",
    "ProxyResponse",
    "RateLimitMiddleware",
    "RateLimiter",
    "ServiceProxy",
    "StripClientHeadersMiddleware",
    "bucket_key",
    "limit_for",
    "strip_client_headers",
]
