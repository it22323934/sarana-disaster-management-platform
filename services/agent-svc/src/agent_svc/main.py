"""FastAPI application factory for agent-svc.

Everything structural - logging, tracing, the error shape, correlation propagation,
/healthz, /readyz and /metrics - comes from `sarana_shared.service.create_service_app`.
This file says what this service is and what it depends on, nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from agent_svc import SERVICE_DESCRIPTION, __version__
from agent_svc.adapters.forecast import (
    CoreApiDivisions,
    GovHazardFeeds,
    SqlForecastStore,
)
from agent_svc.adapters.warning import (
    AlertingCatalogue,
    AlertingDispatcher,
    CoreApiTargets,
    NullHistory,
    SqlForecasts,
)
from agent_svc.agents import SPECS
from agent_svc.agents.forecast import graph as forecast_graph
from agent_svc.agents.forecast.ports import HazardWindow
from agent_svc.agents.warning import graph as warning_graph
from agent_svc.api.v1.router import router as v1_router
from agent_svc.config import Settings, get_settings
from agent_svc.consumers import AgentTriggerWorker
from agent_svc.repo import OutboxEvent
from agent_svc.runtime.checkpoint import (
    durable_checkpointer,
    is_durable,
    memory_checkpointer,
)
from agent_svc.runtime.models import SpendTracker
from agent_svc.runtime.registry import REGISTRY
from agent_svc.runtime.tracing import configure_tracing
from sarana_shared.auth.middleware import AuthenticationMiddleware
from sarana_shared.auth.tokens import TokenService
from sarana_shared.db.session import check_connection, create_engine, create_session_factory
from sarana_shared.domain.time import utc_now
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

        for spec in SPECS:
            if spec.name not in REGISTRY.names():
                REGISTRY.register(spec)
        REGISTRY.compile_all(checkpointer)

        # The forecast agent is the one agent whose graph needs live dependencies to be
        # useful, so it is recompiled here with them. Built after `compile_all` rather than
        # instead of it: every other agent gets its ordinary graph, and a failure to wire
        # this one leaves the refusing stand-ins in place, which say what is missing on the
        # first run rather than reporting a quiet day during a cyclone.
        forecast = _build_forecast(resolved, app.state.session_factory, exit_stack)
        if forecast is not None:
            REGISTRY.replace_graph("forecast", forecast(checkpointer))

        # The warning agent, for the same reason and with the same failure mode: without
        # its dependencies it keeps the refusing stand-ins, which say what is missing on
        # the first run rather than completing a run that sent nothing.
        warning = _build_warning(resolved, app.state.session_factory, exit_stack)
        if warning is not None:
            REGISTRY.replace_graph("warning", warning(checkpointer))

        app.state.agents = REGISTRY

        # Most runs start here rather than from a click: an event arrives and an agent
        # picks it up. Started after the registry is compiled, because a trigger firing
        # against a registry with no graphs in it would be a KeyError on the first report
        # of the day.
        triggers = AgentTriggerWorker(app.state.session_factory, bus=bus, registry=REGISTRY)
        triggers.start()
        app.state.trigger_worker = triggers

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
            await triggers.stop()
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

    # Verified locally against this service's own public key - never a call to core-api per
    # request, which would make the platform's busiest hour depend on one service being up.
    # Added after the app factory has installed correlation and error handling, so an
    # authentication failure is still a Problem Details response carrying a correlation ID.
    app.add_middleware(AuthenticationMiddleware, tokens=TokenService(resolved.tokens()))

    app.include_router(v1_router, prefix="/api/v1")
    return app


def _build_forecast(
    settings: Settings, session_factory: Any, exit_stack: AsyncExitStack
) -> Callable[[Any], Any] | None:
    """A builder for the forecast graph with its real dependencies, or None.

    None when the credential is missing. The agent then keeps the refusing stand-ins from
    its own module, which raise a sentence naming what to run - rather than scoring every
    division against a default hazard zone and producing a forecast that is confidently
    wrong about which slopes are fragile.
    """
    if not settings.client_secret:
        _log.warning(
            "forecast_agent_unconfigured",
            reason="no SARANA_AGENT_CLIENT_SECRET",
            impact="the forecast agent refuses to run; run `make service-clients` and set "
            "the printed secret",
        )
        return None

    from sarana_shared.adapters.gov.met import MetMockClient
    from sarana_shared.adapters.gov.nbro import NbroMockClient
    from sarana_shared.auth.service_credentials import ServiceCredentials

    feeds = GovHazardFeeds(
        met=MetMockClient(settings.gov_mock_url),
        nbro=NbroMockClient(settings.gov_mock_url),
    )
    directory = CoreApiDivisions(
        settings.core_api_url,
        credentials=ServiceCredentials(
            base_url=settings.core_api_url,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            scope="admin:read",
        ),
    )
    store = SqlForecastStore(session_factory)
    exit_stack.push_async_callback(feeds.aclose)
    exit_stack.push_async_callback(directory.aclose)

    def build(checkpointer: Any) -> Any:
        # `window.now` is set per run by the API, not here. A graph compiled once at boot
        # with a fixed clock would forecast against the moment the process started for as
        # long as it stayed up.
        return forecast_graph.build(
            checkpointer,
            feeds=feeds,
            directory=directory,
            store=store,
            window=HazardWindow("pending", "CYCLONE", utc_now()),
        )

    _log.info("forecast_agent_wired", core_api=settings.core_api_url, feeds=settings.gov_mock_url)
    return build


def _build_warning(
    settings: Settings, session_factory: Any, exit_stack: AsyncExitStack
) -> Callable[[Any], Any] | None:
    """A builder for the warning graph with its real dependencies, or None.

    None when the credential is missing. The agent then keeps the refusing stand-ins from
    its own module, which raise a sentence naming what to run - rather than completing a
    run that warned nobody, which from the outside is indistinguishable from a quiet day.
    """
    if not settings.client_secret:
        _log.warning(
            "warning_agent_unconfigured",
            reason="no SARANA_AGENT_CLIENT_SECRET",
            impact="the warning agent refuses to run; run `make service-clients` and set "
            "the printed secret",
        )
        return None

    from sarana_shared.auth.service_credentials import ServiceCredentials

    # Bound here rather than read inside `credentials`: the guard above narrows it to a
    # str, and a closure over `settings` would lose that narrowing.
    secret = settings.client_secret

    def credentials(scope: str) -> ServiceCredentials:
        return ServiceCredentials(
            base_url=settings.core_api_url,
            client_id=settings.client_id,
            client_secret=secret,
            scope=scope,
        )

    # Three grants, kept separate rather than requested as one. They are the same machine
    # identity, and a token audit that can see this service holds `household:contact_read`
    # independently of `alert:dispatch` is one somebody can actually reason about.
    catalogue = AlertingCatalogue(settings.alerting_url, credentials=credentials("alert:read"))
    targets = CoreApiTargets(
        settings.core_api_url, credentials=credentials("household:contact_read admin:read")
    )
    dispatcher = AlertingDispatcher(
        settings.alerting_url, credentials=credentials("alert:draft alert:dispatch")
    )
    forecasts = SqlForecasts(session_factory)

    for adapter in (catalogue, targets, dispatcher):
        exit_stack.push_async_callback(adapter.aclose)

    def build(checkpointer: Any) -> Any:
        # `now` is deliberately not pinned here. The quiet-hours rule is a claim about the
        # hour a run happens, and a graph compiled once at boot with a fixed clock would
        # apply whatever hour the process started for as long as it stayed up - which is
        # exactly the bug that sends a watch-level SMS at 2 a.m.
        return warning_graph.build(
            checkpointer,
            forecasts=forecasts,
            catalogue=catalogue,
            directory=targets,
            dispatcher=dispatcher,
            history=NullHistory(),
            sender=settings.cap_sender,
        )

    _log.info("warning_agent_wired", core_api=settings.core_api_url, alerting=settings.alerting_url)
    return build


def _redis_probe(redis: Redis) -> Callable[[], Awaitable[bool]]:
    """Build a readiness check that pings Redis without propagating a failure."""

    async def probe() -> bool:
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            return False

    return probe
