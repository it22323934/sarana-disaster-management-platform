"""Failure injection, on by default.

Real government APIs are slow, go down, paginate badly, and return an HTML error page
where they promised JSON. Code that has only ever met a perfect mock discovers all of that
at the same time, in production, during a cyclone. So the mock misbehaves on purpose, and
it does so **by default** rather than behind a flag somebody has to remember to set: if the
platform only works at 0%, it is not built.

Four independent injections, each with its own rate:

  **timeout** — the request genuinely hangs. Not a fast 504: a client's timeout handling is
  only exercised by something that actually fails to answer.
  **error** — an upstream 5xx.
  **malformed** — a 200 carrying a body that is not the JSON it claims to be. Modelled on
  the real failure: an HTML error page served with the wrong status.
  **stale** — a well-formed answer computed from an earlier simulated instant. The nastiest
  of the four, because nothing about the response looks wrong.

Plus a flat `latency_ms` on every call, because a government API answering in a
millisecond teaches the wrong lesson about what a fan-out costs.

**The control plane is exempt, and that is not a detail.** `/mock/v1/*` never has chaos
applied to it. Injecting failures into the endpoint that turns injection off would make
100% chaos an unrecoverable state, and the first person to try it would have to restart
the container to get their demo back.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Final

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from sarana_shared.adapters.gov.base import MOCK_HEADER, MOCK_HEADER_VALUE

_log = structlog.get_logger(__name__)

# Never injected into. The operational endpoints an orchestrator probes, the docs, the
# demo simulator page, and above all the control plane that can switch chaos back off.
EXEMPT_PREFIXES: Final[tuple[str, ...]] = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/mock/v1/",
    "/telco/sim",
)

# What a real gateway returns when it falls over: an HTML error page, served as though it
# were the API response the caller asked for.
MALFORMED_BODY: Final = (
    "<html><head><title>502 Bad Gateway</title></head>"
    "<body><h1>Bad Gateway</h1><p>The upstream server did not respond.</p></body></html>"
)


@dataclass(frozen=True, slots=True)
class ChaosConfig:
    """How badly each mock behaves. Percentages, 0-100.

    The 5% defaults come from build file 11. They are per-injection and independent, so
    roughly one call in five is degraded in some way — which is about right for a rural
    district talking to a government API on a bad day, and uncomfortable enough that
    nobody builds a happy path and calls it done.
    """

    timeout_pct: float = 5.0
    error_pct: float = 5.0
    malformed_pct: float = 5.0
    stale_pct: float = 5.0
    latency_ms: int = 250

    # How long a "timeout" holds the connection open. Longer than any adapter's read
    # timeout in `sarana_shared.adapters.gov.base`, so the client gives up first — which
    # is the behaviour under test. Tests lower both ends rather than waiting 30 seconds.
    timeout_hold_seconds: float = 30.0

    # How far back a "stale" response is computed from. Three hours of a cyclone is the
    # difference between a warning and a rescue.
    stale_window_hours: float = 3.0

    def __post_init__(self) -> None:
        for name in ("timeout_pct", "error_pct", "malformed_pct", "stale_pct"):
            value = getattr(self, name)
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be between 0 and 100, got {value}")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

    @property
    def any_active(self) -> bool:
        """Whether any injection is switched on."""
        return bool(self.timeout_pct or self.error_pct or self.malformed_pct or self.stale_pct)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "timeout_pct": self.timeout_pct,
            "error_pct": self.error_pct,
            "malformed_pct": self.malformed_pct,
            "stale_pct": self.stale_pct,
            "latency_ms": self.latency_ms,
            "timeout_hold_seconds": self.timeout_hold_seconds,
            "stale_window_hours": self.stale_window_hours,
        }


# The four injections that can be switched off entirely, in the order they are evaluated.
QUIET: Final = ChaosConfig(timeout_pct=0.0, error_pct=0.0, malformed_pct=0.0, stale_pct=0.0)


class ChaosController:
    """Holds the current chaos settings and the RNG that draws against them.

    One RNG for the whole service, seeded from `SARANA_GOV_MOCK_SEED`, so a demo replayed
    from a fresh container hits the same failures in the same order. A per-request RNG
    would make every call independent and every replay different, which is the one thing a
    demo cannot afford.
    """

    def __init__(self, config: ChaosConfig | None = None, *, seed: int = 20251128) -> None:
        self._config = config or ChaosConfig()
        self._seed = seed
        self._random = random.Random(seed)  # noqa: S311 - failure injection, not a secret
        self.injections: dict[str, int] = {
            "timeout": 0,
            "error": 0,
            "malformed": 0,
            "stale": 0,
        }

    @property
    def config(self) -> ChaosConfig:
        return self._config

    def configure(self, **changes: float | int) -> ChaosConfig:
        """Replace the settings named, keep the rest, and reseed.

        Reseeding on every change is deliberate: it means "set 100% timeout, observe,
        set it back" leaves the sequence where it started rather than a few draws along,
        so a scenario replayed after a chaos experiment is still the same scenario.
        """
        self._config = replace(self._config, **changes)  # type: ignore[arg-type]
        self._random = random.Random(self._seed)  # noqa: S311 - failure injection
        return self._config

    def reset(self) -> None:
        """Back to the configured defaults, counters cleared."""
        self._random = random.Random(self._seed)  # noqa: S311 - failure injection
        for key in self.injections:
            self.injections[key] = 0

    def _draws(self, percent: float) -> bool:
        if percent <= 0.0:
            return False
        return self._random.uniform(0.0, 100.0) < percent

    def next_injection(self) -> str | None:
        """Which failure, if any, this request gets.

        At most one per request. Stacking a timeout on top of a malformed body would make
        the counters unreadable and tells you nothing the individual injections do not.
        """
        for name, percent in (
            ("timeout", self._config.timeout_pct),
            ("error", self._config.error_pct),
            ("malformed", self._config.malformed_pct),
            ("stale", self._config.stale_pct),
        ):
            if self._draws(percent):
                self.injections[name] += 1
                return name
        return None


class ChaosMiddleware(BaseHTTPMiddleware):
    """Applies the controller's decision to each request.

    Returns responses rather than raising. Starlette installs exception handlers inside
    the app, below user middleware, so an exception raised here would escape as an
    unhandled 500 that no handler ever shapes.
    """

    def __init__(self, app: ASGIApp, *, controller: ChaosController) -> None:
        super().__init__(app)
        self._controller = controller

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Set before the exemption check so a handler can always read it. Without this,
        # every handler would need `getattr(request.state, ...)` with a default.
        request.state.chaos_stale = False

        path = request.url.path
        if path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        config = self._controller.config
        injection = self._controller.next_injection()

        if injection == "timeout":
            _log.info("chaos_injected", injection="timeout", path=path)
            await asyncio.sleep(config.timeout_hold_seconds)
            # If the client is still there after the hold, tell it the truth. A caller
            # that set no timeout of its own deserves an answer rather than a hang.
            return _mock_response(
                JSONResponse(
                    {"source": "MOCK", "error": "upstream timeout (injected)"},
                    status_code=504,
                )
            )

        if injection == "error":
            _log.info("chaos_injected", injection="error", path=path)
            return _mock_response(
                JSONResponse(
                    {"source": "MOCK", "error": "upstream failure (injected)"},
                    status_code=503,
                )
            )

        if injection == "malformed":
            _log.info("chaos_injected", injection="malformed", path=path)
            return _mock_response(
                Response(content=MALFORMED_BODY, status_code=200, media_type="application/json")
            )

        if injection == "stale":
            # Handlers read this through the `simulated_now` dependency and compute from
            # an earlier instant. Nothing about the response looks wrong, which is the
            # point: this is the failure that gets believed.
            _log.info("chaos_injected", injection="stale", path=path)
            request.state.chaos_stale = True

        if config.latency_ms:
            await asyncio.sleep(config.latency_ms / 1000.0)

        return await call_next(request)


class MockMarkerMiddleware(BaseHTTPMiddleware):
    """Stamp `X-Sarana-Mock: true` on every response this service produces.

    Mounted outermost, so it covers what `mock_json` cannot: a 404 from the router, a
    validation failure shaped by the shared exception handlers, and the failures the chaos
    middleware injects. The guarantee is then unconditional and has no exceptions to
    reason about — every byte that leaves this service says it came from a mock.

    `mock_json` and `mock_xml` still set the header themselves. That is deliberate
    redundancy rather than an oversight: they are the pair that has to stay in step with
    `sarana_shared.adapters.gov`, and a route tested in isolation should carry the marker
    without depending on middleware being mounted.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers[MOCK_HEADER] = MOCK_HEADER_VALUE
        return response


def _mock_response(response: Response) -> Response:
    """Stamp the mock header on a response the middleware built itself.

    Chaos responses bypass the handlers that would normally stamp it. Without this a
    client would report "that was not a mock" for what is really an injected failure, and
    the injection would be indistinguishable from a misconfigured base URL.
    """
    response.headers[MOCK_HEADER] = MOCK_HEADER_VALUE
    return response
