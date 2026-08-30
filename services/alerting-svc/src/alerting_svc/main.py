"""FastAPI application factory for alerting-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from alerting_svc import SERVICE_DESCRIPTION, __version__
from alerting_svc.adapters.channels.lora import SimulatedMesh
from alerting_svc.adapters.channels.mock_gateways import (
    InAppChannel,
    ManualChannel,
    MockPushService,
    MockSmsGateway,
    MockUssdPush,
)
from alerting_svc.adapters.households import build_directory
from alerting_svc.api.internal.dlr import router as dlr_router
from alerting_svc.api.v1.router import router as v1_router
from alerting_svc.config import Settings, get_settings
from alerting_svc.repo import OutboxEvent
from alerting_svc.workers.payment_notices import PaymentNoticeWorker
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.events.outbox import OutboxPublisher, OutboxWorker
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

SERVICE_NAME = "alerting-svc"

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

        # Every channel is a mock or a simulation in Phase 1. The receipts say so, the
        # console badges the mesh tier, and nothing infers "real" from a channel name.
        app.state.channels = [
            MockSmsGateway(),
            MockUssdPush(),
            MockPushService(),
            InAppChannel(),
            SimulatedMesh(),
            ManualChannel(),
        ]

        # Drains this service's outbox onto the bus. The outbox is the source of truth;
        # this is only the transport, so a worker that dies loses nothing - the rows are
        # still there for the next process to pick up.
        publisher = OutboxPublisher(app.state.session_factory, bus, OutboxEvent)
        worker = OutboxWorker(publisher)
        worker.start()
        app.state.outbox_publisher = publisher
        app.state.outbox_worker = worker

        # Turns a payment the ledger recorded into a message somebody receives. Without
        # this consumer the confirmation loop does not exist: the ledger records what the
        # state believes it paid, and nothing ever asks the household whether it arrived.
        directory = build_directory(
            core_api_url=resolved.core_api_url,
            client_id=resolved.client_id,
            client_secret=resolved.client_secret,
        )
        app.state.household_directory = directory

        notices: PaymentNoticeWorker | None = None
        if resolved.payment_notices_enabled:
            notices = PaymentNoticeWorker(
                app.state.session_factory,
                bus=bus,
                directory=directory,
                # SMS. The one channel a household with a feature phone actually has, and
                # the one the YES/NO reply comes back on.
                channel=app.state.channels[0],
            )
            notices.start()
        app.state.payment_notice_worker = notices

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            if notices is not None:
                await notices.stop()
            await directory.aclose()
            await worker.stop()
            await bus.close()
            await redis.aclose()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Alerting Service",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))

    app.include_router(v1_router, prefix="/api/v1")
    # Telco delivery-receipt webhooks. Service-to-service, never a browser.
    app.include_router(dlr_router)
    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
