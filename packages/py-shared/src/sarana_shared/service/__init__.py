"""Shared FastAPI wiring: app factory, operational endpoints, middleware."""

from sarana_shared.service.app import LifespanHook, create_service_app
from sarana_shared.service.health import (
    HealthRegistry,
    HealthResponse,
    ReadinessCheck,
    ReadinessResponse,
    build_health_router,
)
from sarana_shared.service.middleware import (
    CORRELATION_HEADER,
    AccessLogMiddleware,
    CorrelationMiddleware,
)

__all__ = [
    "CORRELATION_HEADER",
    "AccessLogMiddleware",
    "CorrelationMiddleware",
    "HealthRegistry",
    "HealthResponse",
    "LifespanHook",
    "ReadinessCheck",
    "ReadinessResponse",
    "build_health_router",
    "create_service_app",
]
