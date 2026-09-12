"""A circuit breaker per downstream service.

The point is not to protect the downstream - it is already struggling - but to stop
core-api from spending its own connection pool and its clients' patience on calls that
are going to fail. A service holding 200 requests open against a dead downstream is a
service that has stopped answering the ones it could have served from cache.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import structlog

from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

# Five consecutive failures, then thirty seconds before a single probe. Both from the
# build brief; they are deliberately not tunable per request.
FAILURE_THRESHOLD: Final = 5
RECOVERY_SECONDS: Final = 30.0


class BreakerState(StrEnum):
    """Closed passes traffic, open refuses it, half-open allows one probe."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpen(Exception):
    """The breaker refused the call before it was attempted."""

    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(
            f"circuit for {name} is open; not attempting the call. "
            f"Retry in {retry_after:.0f}s or serve from cache."
        )
        self.name = name
        self.retry_after = retry_after


@dataclass
class CircuitBreaker:
    """One breaker, guarding one downstream.

    Half-open admits exactly one probe. Letting the full load back in at once is how a
    recovering service is knocked straight over again.
    """

    name: str
    failure_threshold: int = FAILURE_THRESHOLD
    recovery_seconds: float = RECOVERY_SECONDS

    _state: BreakerState = BreakerState.CLOSED
    _consecutive_failures: int = 0
    _opened_at: float | None = None
    _probe_in_flight: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @staticmethod
    def _now() -> float:
        return utc_now().timestamp()

    def _retry_after(self, now: float) -> float:
        if self._opened_at is None:
            return 0.0
        return max(0.0, self.recovery_seconds - (now - self._opened_at))

    async def before_call(self) -> None:
        """Refuse fast if the circuit is open.

        Raises:
            CircuitOpen: if the call must not be attempted.
        """
        async with self._lock:
            now = self._now()

            if self._state is BreakerState.OPEN:
                if self._retry_after(now) > 0:
                    raise CircuitOpen(self.name, self._retry_after(now))
                self._state = BreakerState.HALF_OPEN
                self._probe_in_flight = False
                _log.info("circuit_half_open", downstream=self.name)

            if self._state is BreakerState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpen(self.name, self._retry_after(now))
                self._probe_in_flight = True

    async def record_success(self) -> None:
        """A call came back. Close the circuit and forget the failures."""
        async with self._lock:
            if self._state is not BreakerState.CLOSED:
                _log.info("circuit_closed", downstream=self.name)
            self._state = BreakerState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        """A call failed. Open the circuit once the threshold is reached.

        A failed probe from half-open reopens immediately rather than counting toward the
        threshold again: the probe existed to answer exactly this question.
        """
        async with self._lock:
            self._probe_in_flight = False

            if self._state is BreakerState.HALF_OPEN:
                self._state = BreakerState.OPEN
                self._opened_at = self._now()
                _log.warning("circuit_reopened", downstream=self.name)
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = self._now()
                _log.warning(
                    "circuit_opened",
                    downstream=self.name,
                    consecutive_failures=self._consecutive_failures,
                )

    def reset(self) -> None:
        """Force closed. For tests and for an operator who has fixed the downstream."""
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._probe_in_flight = False


class BreakerRegistry:
    """One breaker per downstream, created on first use."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name)
        return self._breakers[name]

    def states(self) -> dict[str, str]:
        """Every breaker's state, for /readyz and the operations console."""
        return {name: breaker.state.value for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()
