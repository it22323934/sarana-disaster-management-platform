"""FastAPI application factory for core-api.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from core_api import SERVICE_DESCRIPTION, __version__
from core_api.api.v1.jwks import build_jwks_router
from core_api.api.v1.router import router as v1_router
from core_api.config import Settings, get_settings
from core_api.domain.auth.password import PasswordHasherService
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.bus import RedisStreamsEventBus
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

SERVICE_NAME = "core-api"

# There is deliberately no module-level `app`. Settings are read inside build_app(),
# so importing this module in a test does not exit the process when the environment
# is incomplete. uvicorn is started with --factory.


def build_app(settings: Settings | None = None) -> FastAPI:
    """Construct the application. Tests call this directly with their own settings."""
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI, health: HealthRegistry) -> AsyncIterator[None]:
        engine = create_engine(resolved.database(application_name=SERVICE_NAME))
        redis = Redis.from_url(resolved.redis_url)
        bus = RedisStreamsEventBus(redis, prefix=resolved.event_stream_prefix)

        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.event_bus = bus

        # core-api is the only token issuer: it is the only service configured with a
        # private key. Everything else verifies against the JWKS this service publishes.
        app.state.tokens = TokenService(resolved.tokens(can_issue=True))
        app.state.password_hasher = PasswordHasherService.create()
        app.state.keyed_hasher = resolved.keyed_hasher()
        app.state.field_cipher = resolved.field_cipher()

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            await bus.close()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Core API",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )
    # Verified locally against this service's own key. Added after the app factory has
    # installed correlation and error handling, so an authentication failure is still a
    # Problem Details response carrying a correlation ID.
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))

    app.include_router(build_jwks_router(resolved))
    app.include_router(v1_router, prefix="/api/v1")
    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
