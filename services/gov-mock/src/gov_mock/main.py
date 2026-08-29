"""FastAPI application factory for gov-mock.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.

**The routers mount at the root, not under `/api/v1`.** Every other SARANA service serves
its own API under one versioned prefix. This one stands in for seven systems that are not
SARANA, and each of them has its own URL shape: `/met/v1/warnings`, `/ndrsc/v1/claims`,
`/telco/v1/sms/send`. Normalising them under a SARANA prefix would make the mock easier to
mount and would hide exactly what has to be true for the real swap to be a configuration
change.

**gov-mock owns no database tables.** It has a Postgres readiness check because it shares
the platform's compose stack and a broken database is worth surfacing, but nothing here
reads or writes a SARANA schema. See `gov_mock.state` for where the recorded data lives
and why.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from gov_mock import SERVICE_DESCRIPTION, __version__
from gov_mock.api import dmc, met, nbro, ndrsc, pay, registry, scenario, sim, telco
from gov_mock.chaos import (
    ChaosConfig,
    ChaosController,
    ChaosMiddleware,
    MockMarkerMiddleware,
)
from gov_mock.clock import SimulatedClock
from gov_mock.config import Settings, get_settings
from gov_mock.state import MockState
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

_log = structlog.get_logger(__name__)

SERVICE_NAME = "gov-mock"

# There is deliberately no module-level `app`. Settings are read inside build_app(),
# so importing this module in a test does not exit the process when the environment
# is incomplete. uvicorn is started with --factory.


def build_app(settings: Settings | None = None) -> FastAPI:
    """Construct the application. Tests call this directly with their own settings."""
    resolved = settings or get_settings()

    chaos = ChaosController(
        ChaosConfig(
            timeout_pct=resolved.timeout_pct,
            error_pct=resolved.error_pct,
            malformed_pct=resolved.malformed_pct,
            stale_pct=resolved.stale_pct,
            latency_ms=resolved.latency_ms,
        ),
        seed=resolved.seed,
    )
    mock_state = MockState(seed=resolved.seed, clock=SimulatedClock(), chaos=chaos)

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

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        _log.info(
            "gov_mock_ready",
            seed=resolved.seed,
            chaos=chaos.config.as_dict(),
            safety_locations=len(mock_state.locations),
        )

        try:
            yield
        finally:
            await bus.close()
            await redis.aclose()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Government and Telco Mocks",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )

    # Held on the app rather than in a module global so two apps in one test process -
    # one chaotic, one quiet - do not share a clock.
    app.state.mock = mock_state

    # Order matters: `add_middleware` prepends, so the marker is added last and therefore
    # runs outermost. It has to wrap the chaos middleware, otherwise an injected failure
    # would go out unmarked and read as a misconfigured base URL rather than as the
    # injection it is.
    app.add_middleware(ChaosMiddleware, controller=chaos)
    app.add_middleware(MockMarkerMiddleware)

    for router in (
        met.router,
        nbro.router,
        dmc.router,
        ndrsc.router,
        registry.officers_router,
        registry.households_router,
        pay.router,
        telco.router,
        sim.router,
        scenario.router,
    ):
        app.include_router(router)

    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
