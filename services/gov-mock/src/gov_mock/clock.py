"""One simulated clock, shared by every mock in this service.

The rule that makes the whole thing usable: **every mock reads the same clock, and nothing
reads the wall clock.** Rainfall rises, NBRO issues its bulletin, the DMC opens shelters,
occupancy fills and cell coverage degrades against one timeline. Seven mocks each drifting
on their own `datetime.now()` would produce a demo where the bulletin arrives before the
rain, which is the one thing a disaster demo must not do.

The clock is **pinned by default**. `now()` returns the same instant until somebody
advances it, so every generated figure is a pure function of `(seed, offset)`: the same
scenario at `T+6h` produces the same rainfall at the same stations on every machine, in
every test, on every replay of a demo.

`speed` is the seam for file 28's scenario driver. Above zero, simulated time flows at
that multiple of real time from the last anchor — `speed=60.0` runs an hour a minute for a
live demo. It is zero here because a test that has to sleep to observe a value is a test
that will be flaky on somebody's laptop.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sarana_shared.domain.time import format_relative, parse_relative

# Cyclone Ditwah landfall on Sri Lanka's east coast, 28 Nov 2025, 00:00 Colombo. The same
# instant `sarana_shared.testing.fixtures.DITWAH_LANDFALL` anchors, so a scenario fixture
# written against one lines up with the other.
DEFAULT_LANDFALL: Final = datetime(2025, 11, 27, 18, 30, tzinfo=UTC)


@dataclass(slots=True)
class ClockState:
    """A snapshot of where the clock is. Serialised into `GET /mock/v1/state`."""

    landfall_at: datetime
    offset: timedelta
    speed: float

    @property
    def relative(self) -> str:
        """The current position as a landfall-relative offset, e.g. `T+6h`."""
        return format_relative(self.offset)


class SimulatedClock:
    """The clock every mock reads.

    Thread-safe because uvicorn runs request handlers on a thread pool for any sync path,
    and a half-written offset would show up as a single impossible reading in the middle
    of an otherwise sensible rainfall curve — the kind of bug that gets blamed on the
    generator for a day.
    """

    def __init__(
        self,
        *,
        landfall_at: datetime = DEFAULT_LANDFALL,
        offset: timedelta = timedelta(0),
        speed: float = 0.0,
    ) -> None:
        if landfall_at.tzinfo is None:
            raise ValueError("the simulated clock needs a timezone-aware landfall instant")
        if speed < 0:
            raise ValueError("simulated time does not run backwards; speed must be >= 0")

        self._lock = threading.Lock()
        self._landfall_at = landfall_at.astimezone(UTC)
        self._offset = offset
        self._speed = speed
        self._anchored_at = datetime.now(UTC)

    @property
    def landfall_at(self) -> datetime:
        """The instant every offset is measured from."""
        return self._landfall_at

    def now(self) -> datetime:
        """The current simulated instant."""
        return self._landfall_at + self.offset()

    def offset(self) -> timedelta:
        """How far past landfall the simulation has reached."""
        with self._lock:
            if self._speed == 0.0:
                return self._offset
            elapsed = (datetime.now(UTC) - self._anchored_at).total_seconds()
            return self._offset + timedelta(seconds=elapsed * self._speed)

    def relative(self) -> str:
        """The current position as a landfall-relative offset."""
        return format_relative(self.offset())

    def advance_to(self, offset: str) -> timedelta:
        """Jump to a landfall-relative offset such as `T+6h`.

        Refuses to move backwards. Rewinding would leave shelters holding people who have
        not yet arrived and a ledger of messages sent in the future; a scenario that needs
        an earlier state reloads rather than rewinds.

        Raises:
            ValueError: if the offset is unparseable or earlier than the current position.
        """
        target = parse_relative(offset)
        with self._lock:
            current = self._offset
            if self._speed != 0.0:
                elapsed = (datetime.now(UTC) - self._anchored_at).total_seconds()
                current = self._offset + timedelta(seconds=elapsed * self._speed)
            if target < current:
                raise ValueError(
                    f"cannot advance to {offset}: the simulation is already at "
                    f"{format_relative(current)}. Reload the scenario to start again."
                )
            self._offset = target
            self._anchored_at = datetime.now(UTC)
            return target

    def reset(
        self,
        *,
        landfall_at: datetime | None = None,
        offset: timedelta = timedelta(0),
        speed: float | None = None,
    ) -> None:
        """Put the clock back to the start of a scenario."""
        with self._lock:
            if landfall_at is not None:
                self._landfall_at = landfall_at.astimezone(UTC)
            if speed is not None:
                if speed < 0:
                    raise ValueError("simulated time does not run backwards; speed must be >= 0")
                self._speed = speed
            self._offset = offset
            self._anchored_at = datetime.now(UTC)

    def set_speed(self, speed: float) -> None:
        """Change how fast simulated time runs, keeping the current position."""
        if speed < 0:
            raise ValueError("simulated time does not run backwards; speed must be >= 0")
        with self._lock:
            if self._speed != 0.0:
                elapsed = (datetime.now(UTC) - self._anchored_at).total_seconds()
                self._offset += timedelta(seconds=elapsed * self._speed)
            self._speed = speed
            self._anchored_at = datetime.now(UTC)

    def state(self) -> ClockState:
        """A snapshot for `GET /mock/v1/state`."""
        with self._lock:
            speed = self._speed
            landfall = self._landfall_at
        return ClockState(landfall_at=landfall, offset=self.offset(), speed=speed)

    def hours_since_landfall(self) -> float:
        """The current offset in hours. What the rainfall curves are keyed on."""
        return self.offset().total_seconds() / 3600.0
