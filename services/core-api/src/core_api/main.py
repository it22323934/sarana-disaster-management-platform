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
from core_api.api.internal.audit import router as internal_router
from core_api.api.v1.jwks import build_jwks_router
from core_api.api.v1.router import router as v1_router
from core_api.cache import TTLCache
from core_api.config import Settings, get_settings
from core_api.domain.auth.password import PasswordHasherService
from core_api.gateway import (
    BreakerRegistry,
    InternalPrincipalMinter,
    RateLimitMiddleware,
    ServiceProxy,
    StripClientHeadersMiddleware,
)
from core_api.repo import OutboxEvent
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.events.outbox import OutboxPublisher, OutboxWorker
from sarana_shared.events.replay import ReplayCoordinator
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

SERVICE_NAME = "core-api"

# The resolve cache holds one entry per rounded coordinate. Sri Lanka has ~14,022 GN
# divisions and reports cluster hard, so this covers a national-scale event comfortably
# while staying bounded.
RESOLVE_CACHE_ENTRIES = 50_000
RESOLVE_CACHE_TTL_SECONDS = 3600.0

# There is deliberately no module-level `app`. Settings are read inside build_app(),
# so importing this module in a test does not exit the process when the environment
# is incomplete. uvicorn is started with --factory.


def build_app(settings: Settings | None = None) -> FastAPI:
    """Construct the application. Tests call this directly with their own settings."""
    resolved = settings or get_settings()

    # core-api is the only service that signs, so the private key is mandatory here even
    # though the shared settings make it optional. Failing at construction names the
    # variable; the alternative is a None reaching the signer mid-incident.
    if resolved.jwt_private_key_path is None:
        raise ValueError(
            "SARANA_JWT_PRIVATE_KEY_PATH is required for core-api: it is the only token "
            "issuer and mints the internal principal header the gateway forwards."
        )
    private_key_path = resolved.jwt_private_key_path

    @asynccontextmanager
    async def lifespan(app: FastAPI, health: HealthRegistry) -> AsyncIterator[None]:
        engine = create_engine(resolved.database(application_name=SERVICE_NAME))
        redis = Redis.from_url(resolved.redis_url)
        bus = build_event_bus(
            kind=resolved.event_bus,
            redis_url=resolved.redis_url,
            stream_prefix=resolved.event_stream_prefix,
            bus_name=resolved.event_bus_name,
            region=resolved.aws_region,
        )

        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.event_bus = bus

        # The hot path. Every citizen report resolves a coordinate to a GN division, and
        # the answer for a given rounded coordinate never changes between census cycles.
        app.state.resolve_cache = TTLCache(
            max_entries=RESOLVE_CACHE_ENTRIES, ttl_seconds=RESOLVE_CACHE_TTL_SECONDS
        )

        # One breaker per downstream, plus the proxy that consults them. Built here so a
        # breaker's state survives for the process rather than per request.
        breakers = BreakerRegistry()
        app.state.breakers = breakers
        app.state.proxy = ServiceProxy(
            downstreams=resolved.downstreams(),
            minter=InternalPrincipalMinter(private_key_path, issuer=resolved.jwt_issuer),
            breakers=breakers,
        )

        # Drains this service's outbox onto the bus. The outbox is the source of truth;
        # this is only the transport, so a worker that dies loses nothing - the rows are
        # still there for the next process to pick up.
        publisher = OutboxPublisher(app.state.session_factory, bus, OutboxEvent)
        worker = OutboxWorker(publisher)
        worker.start()
        app.state.outbox_publisher = publisher
        app.state.outbox_worker = worker

        # One replay at a time, per process. The constraint is the safety feature:
        # an operator starting a replay during an incident should have to notice
        # that one is already running rather than quietly stacking a second.
        app.state.replay_coordinator = ReplayCoordinator(bus=bus)

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
            await worker.stop()
            await app.state.proxy.aclose()
            await bus.close()
            await redis.aclose()
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
    # Starlette runs middleware in reverse order of registration, so these three are added
    # last-to-first. The resulting order is deliberate and load-bearing:
    #
    #   1. StripClientHeaders - before anything reads a header, so no later component can
    #      be fooled by a client-supplied X-Sarana-Principal.
    #   2. Authentication     - resolves the principal.
    #   3. RateLimit          - needs that principal, because the allowance depends on who
    #      is calling; an anonymous limit applied to an operator would throttle the console.
    app.add_middleware(RateLimitMiddleware)
    # Verified locally against this service's own key. Added after the app factory has
    # installed correlation and error handling, so an authentication failure is still a
    # Problem Details response carrying a correlation ID.
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))
    app.add_middleware(StripClientHeadersMiddleware)

    app.include_router(build_jwks_router(resolved))
    app.include_router(v1_router, prefix="/api/v1")
    # Mounted outside /api/v1: service-to-service only.
    app.include_router(internal_router)
    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
