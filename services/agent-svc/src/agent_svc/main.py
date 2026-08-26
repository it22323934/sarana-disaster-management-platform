"""FastAPI application factory for agent-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from agent_svc import SERVICE_DESCRIPTION, __version__
from agent_svc.api.v1.router import router as v1_router
from agent_svc.config import Settings, get_settings
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.bus import RedisStreamsEventBus
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

SERVICE_NAME = "agent-svc"

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

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            await bus.close()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Agent Service",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )
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
