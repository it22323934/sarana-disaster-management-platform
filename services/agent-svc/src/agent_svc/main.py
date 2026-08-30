"""FastAPI application factory for agent-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from agent_svc import SERVICE_DESCRIPTION, __version__
from agent_svc.agents.noop import SPEC as NOOP_SPEC
from agent_svc.api.v1.router import router as v1_router
from agent_svc.config import Settings, get_settings
from agent_svc.repo import OutboxEvent
from agent_svc.runtime.checkpoint import (
    durable_checkpointer,
    is_durable,
    memory_checkpointer,
)
from agent_svc.runtime.models import SpendTracker
from agent_svc.runtime.registry import REGISTRY
from agent_svc.runtime.tracing import configure_tracing
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.events.factory import build_event_bus
from sarana_shared.events.outbox import OutboxPublisher, OutboxWorker
from sarana_shared.service.app import create_service_app
from sarana_shared.service.health import HealthRegistry

_log = structlog.get_logger(__name__)

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

        # The checkpointer is what makes a paused run survive a redeploy. An in-process
        # one loses every pending approval on restart, so a deployment that ends up with
        # one says so on its first log line rather than on the first interrupt that never
        # comes back.
        exit_stack = AsyncExitStack()
        if resolved.durable_checkpoints:
            checkpointer = await exit_stack.enter_async_context(
                durable_checkpointer(resolved.database_url)
            )
        else:
            checkpointer = memory_checkpointer()
        if not is_durable(checkpointer):
            _log.warning(
                "agent_checkpoints_not_durable",
                impact="every run paused on a human decision is lost when this process "
                "restarts; set SARANA_AGENT_DURABLE_CHECKPOINTS=true",
            )
        app.state.checkpointer = checkpointer

        if NOOP_SPEC.name not in REGISTRY.names():
            REGISTRY.register(NOOP_SPEC)
        REGISTRY.compile_all(checkpointer)
        app.state.agents = REGISTRY

        app.state.spend = SpendTracker(daily_cap_usd=resolved.daily_spend_cap_usd)
        configure_tracing(
            enabled=resolved.tracing,
            project=resolved.langsmith_project,
            api_key=resolved.langsmith_api_key,
        )
        if not resolved.openai_api_key:
            _log.warning(
                "agent_model_provider_unconfigured",
                impact="every agent runs its deterministic path and labels the output "
                "DETERMINISTIC; this is the same code a provider outage falls back to",
            )

        health.register("database", lambda: check_connection(engine))
        health.register("event_bus", _redis_probe(redis))

        try:
            yield
        finally:
            await exit_stack.aclose()
            await worker.stop()
            await bus.close()
            await redis.aclose()
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
