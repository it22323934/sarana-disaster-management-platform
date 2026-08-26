"""The shared FastAPI app factory.

Every service calls `create_service_app` and then mounts its own routers. Keeping the
wiring here means logging, tracing, error shape, correlation propagation and the three
operational endpoints are identical across all six services by construction, not by six
copies that drift.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sarana_shared.config import SharedSettings
from sarana_shared.errors import install_exception_handlers
from sarana_shared.service.health import HealthRegistry, build_health_router
from sarana_shared.service.middleware import AccessLogMiddleware, CorrelationMiddleware
from sarana_shared.telemetry.logging import configure_logging
from sarana_shared.telemetry.tracing import (
    configure_tracing,
    instrument_app,
    shutdown_tracing,
)

_log = structlog.get_logger(__name__)

# Lifespan hook signature: receives the app and the health registry, so a service can
# register its readiness checks against the resources it just opened.
LifespanHook = Callable[[FastAPI, HealthRegistry], AbstractAsyncContextManager[None]]


def create_service_app(
    *,
    service: str,
    title: str,
    description: str,
    version: str,
    settings: SharedSettings,
    lifespan_hook: LifespanHook | None = None,
    cors_origins: list[str] | None = None,
    openapi_tags: list[dict[str, Any]] | None = None,
) -> tuple[FastAPI, HealthRegistry]:
    """Build a configured FastAPI app and its health registry.

    Returns both so the caller can register readiness checks and mount routers. The
    service's `main.py` is then a short file that says what this service is, not how a
    FastAPI app is assembled.
    """
    configure_logging(service=service, level=settings.log_level, json_output=settings.json_logs)
    configure_tracing(
        service=service,
        version=version,
        environment=settings.env.value,
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.tracing_enabled,
    )

    registry = HealthRegistry(service=service, version=version)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _log.info(
            "service_starting",
            service=service,
            version=version,
            environment=settings.env.value,
            instance=settings.instance,
        )
        if lifespan_hook is None:
            yield
        else:
            async with lifespan_hook(app, registry):
                yield
        shutdown_tracing()
        _log.info("service_stopped", service=service)

    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        openapi_tags=openapi_tags,
        # Problem Details, not FastAPI's default {"detail": ...}.
        responses={
            400: {"description": "Problem Details", "content": {"application/problem+json": {}}},
            401: {"description": "Problem Details", "content": {"application/problem+json": {}}},
            403: {"description": "Problem Details", "content": {"application/problem+json": {}}},
            404: {"description": "Problem Details", "content": {"application/problem+json": {}}},
            422: {"description": "Problem Details", "content": {"application/problem+json": {}}},
        },
    )

    # Middleware runs bottom-up, so correlation is added last and therefore runs first.
    app.add_middleware(AccessLogMiddleware, service=service)
    app.add_middleware(CorrelationMiddleware)

    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Correlation-Id"],
        )

    install_exception_handlers(app)
    instrument_app(app)
    app.include_router(build_health_router(registry))

    app.state.settings = settings
    app.state.health = registry

    return app, registry
