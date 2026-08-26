"""core-api — gateway, admin hierarchy, Resilience Graph, audit log.

FastAPI app factory + lifespan + router mounting only, per
docs/build-prompts/03-monorepo-scaffold.md ("Out of scope: business logic of any kind").
The gateway routing, hierarchy endpoints, Resilience Graph API, and audit log are
docs/build-prompts/07-core-api.md's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from sarana_shared.db.session import make_engine, make_session_factory
from sarana_shared.errors import register_exception_handlers
from sarana_shared.telemetry.logging import configure_logging, get_logger
from sarana_shared.telemetry.tracing import configure_tracing, instrument_fastapi
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core_api.config import Settings, get_settings

SERVICE_NAME = "core-api"


@dataclass
class AppState:
    """Everything a request handler might need, off `request.app.state` — no module-level
    globals, so tests can construct a fresh instance per app without import-order tricks."""

    settings: Settings
    db_engine: AsyncEngine


async def check_database(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def make_health_router(state: AppState) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Liveness only — must stay up even if the database is unreachable, so the
        # container isn't killed and restarted into a thundering herd
        # (docs/build-prompts/07-core-api.md).
        return {"status": "ok", "service": SERVICE_NAME}

    @router.get("/readyz")
    async def readyz() -> dict[str, str | bool]:
        db_ok = await check_database(state.db_engine)
        # TODO(file 06): also check the event bus once a real EventBus is wired in.
        return {"status": "ok" if db_ok else "degraded", "database": db_ok}

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    engine = make_engine(resolved_settings.database_url)
    make_session_factory(engine)  # constructed here so a bad DB URL fails at startup
    state = AppState(settings=resolved_settings, db_engine=engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(service=SERVICE_NAME, level=resolved_settings.log_level)
        configure_tracing(
            service=SERVICE_NAME,
            otlp_endpoint=resolved_settings.otel_exporter_otlp_endpoint,
        )
        logger = get_logger()
        logger.info("service_starting", service=SERVICE_NAME, port=resolved_settings.port)
        yield
        logger.info("service_stopping", service=SERVICE_NAME)
        await engine.dispose()

    app = FastAPI(title="SARANA core-api", lifespan=lifespan)
    app.state.app_state = state

    register_exception_handlers(app)
    app.include_router(make_health_router(state))
    # api/v1 routers are mounted here once docs/build-prompts/07-core-api.md builds them.

    instrument_fastapi(app, engine.sync_engine)
    return app


app = create_app()
