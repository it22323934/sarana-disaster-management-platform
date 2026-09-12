"""Liveness, readiness and metrics - the three endpoints every service exposes.

/healthz  liveness. Answers only "is this process running". Never touches a
          dependency: a database blip must not cause the orchestrator to kill and
          restart an otherwise healthy replica.
/readyz   readiness. Checks the database and the event bus. Failing here removes the
          replica from the load balancer without restarting it.
/metrics  Prometheus exposition.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from pydantic import BaseModel, ConfigDict

_log = structlog.get_logger(__name__)

# name -> async predicate. False or a raised exception both mean "not ready".
ReadinessCheck = Callable[[], Awaitable[bool]]


class HealthResponse(BaseModel):
    """Liveness payload."""

    model_config = ConfigDict(frozen=True)

    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Readiness payload, naming each dependency so a failure is diagnosable."""

    model_config = ConfigDict(frozen=True)

    status: str
    service: str
    checks: dict[str, bool]


@dataclass
class HealthRegistry:
    """The readiness checks a service has registered.

    Services add checks during lifespan startup, once the resource actually exists -
    registering a database check before the engine is built would report ready too early.
    """

    service: str
    version: str
    checks: dict[str, ReadinessCheck] = field(default_factory=dict)

    def register(self, name: str, check: ReadinessCheck) -> None:
        """Add a named readiness check."""
        self.checks[name] = check

    async def evaluate(self) -> dict[str, bool]:
        """Run every check. An exception counts as a failure, never as a crash."""
        results: dict[str, bool] = {}
        for name, check in self.checks.items():
            try:
                results[name] = bool(await check())
            except Exception:  # noqa: BLE001 - a probe reports, it does not propagate
                _log.warning("readiness_check_failed", check=name, exc_info=True)
                results[name] = False
        return results


def build_health_router(
    registry: HealthRegistry,
    metrics_registry: CollectorRegistry | None = None,
) -> APIRouter:
    """Build the router carrying all three endpoints.

    Excluded from the OpenAPI schema: they are operational surface, not API surface, and
    they would otherwise appear in the generated TypeScript client.
    """
    router = APIRouter(tags=["operations"], include_in_schema=False)

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok", service=registry.service, version=registry.version)

    @router.get("/readyz", response_model=ReadinessResponse)
    async def readyz(response: Response) -> ReadinessResponse:
        results = await registry.evaluate()
        ready = all(results.values())
        if not ready:
            response.status_code = 503
        return ReadinessResponse(
            status="ready" if ready else "not_ready",
            service=registry.service,
            checks=results,
        )

    @router.get("/metrics")
    async def metrics() -> Response:
        payload = generate_latest(metrics_registry) if metrics_registry else generate_latest()
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

    return router
