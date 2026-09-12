"""FastAPI application factory for ledger-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from ledger_svc import SERVICE_DESCRIPTION, __version__
from ledger_svc.api.internal import router as internal_router
from ledger_svc.api.v1.router import router as v1_router
from ledger_svc.config import Settings, get_settings
from ledger_svc.repo import OutboxEvent
from ledger_svc.workers.anchor import AnchorWorker
from ledger_svc.workers.settlement import SettlementWorker
from sarana_shared.adapters.gov import build_payment_client
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.events.outbox import OutboxPublisher, OutboxWorker
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

SERVICE_NAME = "ledger-svc"

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

        # Drains this service's outbox onto the bus. The outbox is the source of truth;
        # this is only the transport, so a worker that dies loses nothing - the rows are
        # still there for the next process to pick up.
        publisher = OutboxPublisher(app.state.session_factory, bus, OutboxEvent)
        worker = OutboxWorker(publisher)
        worker.start()
        app.state.outbox_publisher = publisher
        app.state.outbox_worker = worker

        # ADR-005. Builds the daily Merkle root and writes it where the operator cannot
        # change it. It catches up on start, so a process that was down over a midnight
        # does not leave a permanent hole in the public proof.
        anchors = AnchorWorker(app.state.session_factory)
        anchors.start()
        app.state.anchor_worker = anchors

        # Asks the rail what became of every payment whose outcome is still unknown. About
        # three transfers in a hundred are accepted and then returned, and without this
        # nothing in the platform would ever find out: the release is recorded, hashed and
        # published, and the household is at home believing they have been paid.
        settlements: SettlementWorker | None = None
        rail = build_payment_client(base_url=resolved.gov_mock_url)
        if resolved.settlement_poll_seconds > 0:
            settlements = SettlementWorker(
                app.state.session_factory,
                rail=rail,
                interval_seconds=resolved.settlement_poll_seconds,
            )
            settlements.start()
        app.state.settlement_worker = settlements
        app.state.payment_rail = rail

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            if settlements is not None:
                await settlements.stop()
            await rail.aclose()
            await anchors.stop()
            await worker.stop()
            await bus.close()
            await redis.aclose()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Aid Ledger Service",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )

    # Verified locally against this service's own public key - never a call to core-api per
    # request, which would make the platform's busiest hour depend on one service being up.
    # Added after the app factory has installed correlation and error handling, so an
    # authentication failure is still a Problem Details response carrying a correlation ID.
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))

    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(internal_router, prefix="/internal/v1")
    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
