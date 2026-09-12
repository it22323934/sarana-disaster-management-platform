"""FastAPI application factory for incident-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from incident_svc import SERVICE_DESCRIPTION, __version__
from incident_svc.adapters.agent_runtime import AgentThreadResumer
from incident_svc.adapters.core_api import CoreApiClient
from incident_svc.api.internal.channels import router as channels_router
from incident_svc.api.v1.router import router as v1_router
from incident_svc.config import Settings, get_settings
from incident_svc.domain.dispatch_gate import NullResumer
from incident_svc.repo import OutboxEvent
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.service_credentials import ServiceCredentials
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.events.outbox import OutboxPublisher, OutboxWorker
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

_log = structlog.get_logger(__name__)

SERVICE_NAME = "incident-svc"

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

        # Resolving a coordinate to a division is the one core-api call on the intake
        # path. The client caches and degrades: a report that cannot be placed is kept
        # unplaced rather than refused.
        app.state.core_api = CoreApiClient(
            resolved.core_api_url,
            credentials=(
                ServiceCredentials(
                    base_url=resolved.core_api_url,
                    client_id=resolved.client_id,
                    client_secret=resolved.client_secret,
                    scope="admin:read",
                )
                if resolved.client_secret
                else None
            ),
        )

        # Assisted triage is off until the agent runtime exists (build file 12). The queue
        # endpoint reports this verbatim, so a dispatcher is never left believing an
        # ordered list came from a model when it came from the published rule.
        app.state.assisted_triage = False

        # The dispatch gate's resumer. `NullResumer` accepts the resume and reports
        # `graph_resumed: false`, which is the honest answer for a deployment with the
        # agents switched off - a plan proposed without an agent has no thread to resume,
        # and failing closed would mean the gate could not be used at all.
        if resolved.resume_agent_threads:
            app.state.thread_resumer = AgentThreadResumer(resolved.agent_svc_url)
            _log.info("dispatch_resumer_wired", agent_svc=resolved.agent_svc_url)
        else:
            app.state.thread_resumer = NullResumer()
            _log.info(
                "dispatch_resumer_not_wired",
                impact="approving a plan reports graph_resumed: false; the plan is still "
                "released and every gate still holds. Set "
                "SARANA_INCIDENT_RESUME_AGENT_THREADS=true once agent-svc is reachable.",
            )

        # Drains this service's outbox onto the bus. The outbox is the source of truth;
        # this is only the transport, so a worker that dies loses nothing - the rows are
        # still there for the next process to pick up.
        publisher = OutboxPublisher(app.state.session_factory, bus, OutboxEvent)
        worker = OutboxWorker(publisher)
        worker.start()
        app.state.outbox_publisher = publisher
        app.state.outbox_worker = worker

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            await worker.stop()
            if hasattr(app.state.thread_resumer, "aclose"):
                await app.state.thread_resumer.aclose()
            await app.state.core_api.aclose()
            await bus.close()
            await redis.aclose()
            await engine.dispose()

    app, _health = create_service_app(
        service=SERVICE_NAME,
        title="SARANA Incident Service",
        description=SERVICE_DESCRIPTION,
        version=__version__,
        settings=resolved,
        lifespan_hook=lifespan,
        cors_origins=resolved.cors_origins,
    )
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))

    app.include_router(v1_router, prefix="/api/v1")
    # Telco and mesh webhooks. Service-to-service, never reached by a browser.
    app.include_router(channels_router)
    return app


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
