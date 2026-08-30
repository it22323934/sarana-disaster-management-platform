"""What the forecast graph needs from the outside world, as narrow protocols.

Three ports, and they exist so the whole agent runs against fakes. The headline claim - that
Kandy's fragile slopes reach major impact a day before landfall - has to be a test, not a
hope, and a test that needs Postgres, core-api, gov-mock and an OpenAI key is one that runs
in CI on a good day and nowhere else.

Each port is deliberately smaller than the client behind it. `HazardFeeds` does not expose
`MetClient`; it exposes the four questions this agent asks. A port shaped like its adapter is
a port that leaks the adapter's problems into every test that stubs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agent_svc.agents.forecast.exposure import DivisionExposure, StationReading
from agent_svc.agents.forecast.reconcile import SourceClaim
from agent_svc.agents.forecast.scoring import ZoneThresholds


@dataclass(frozen=True, slots=True)
class HazardWindow:
    """The event being forecast, and when.

    `now` is passed rather than read from the clock so a replay can run the agent at
    T-48h and get what the agent would have said at T-48h. An agent that reads
    `datetime.now()` internally cannot be replayed, and an agent that cannot be replayed
    cannot be reviewed after the event - which is the whole Learn loop.
    """

    hazard_event_id: str
    hazard_type: str
    now: datetime
    landfall_at: datetime | None = None

    @property
    def hours_to_landfall(self) -> float | None:
        if self.landfall_at is None:
            return None
        return (self.landfall_at - self.now).total_seconds() / 3600.0


class HazardFeeds(Protocol):
    """The four questions this agent asks the government feeds."""

    async def claims(self, *, district_codes: tuple[str, ...]) -> list[SourceClaim]:
        """Every source's statement about the affected areas, normalised onto one scale.

        Met warnings and NBRO bulletins arrive as different vocabularies on different
        geometries; flattening them to `SourceClaim` is the adapter's job, not the graph's.
        """
        ...

    async def observations(self) -> list[StationReading]:
        """Current station readings, including the stations that are not reporting."""
        ...

    async def district_forecast(self, *, district_code: str, hours: int) -> float:
        """Expected 24-hour rainfall accumulation at the midpoint of a forward window."""
        ...

    async def thresholds(self) -> dict[int, ZoneThresholds]:
        """NBRO's rainfall thresholds, one set per hazard zone."""
        ...

    async def warned_districts(self) -> tuple[str, ...]:
        """The districts any source has issued against.

        What bounds the run. Scoring all 14,022 divisions on every generation would write
        a "no impact expected" row for the whole country several times an hour, and bury
        the forecasts somebody needs to read.
        """
        ...


class DivisionDirectory(Protocol):
    """Where the exposure attributes come from."""

    async def divisions_in(self, district_codes: tuple[str, ...]) -> list[DivisionExposure]:
        """Every GN division in these districts, with its exposure attributes."""
        ...

    async def names(self, gn_division_ids: list[str]) -> dict[str, dict[str, str]]:
        """Trilingual division names, for the narrative.

        Separate from `divisions_in` because the scoring engine has no use for a name and
        carrying three languages of it through the scorer would put text into a checkpoint
        for no reason.
        """
        ...


class ForecastStore(Protocol):
    """Where forecasts and trigger firings are written."""

    async def save_forecasts(self, rows: list[dict[str, Any]]) -> list[str]:
        """Insert forecast rows. Returns their ids, in the order given.

        Ids come back because a trigger firing records the forecast that caused it, and
        without that link an after-action review can establish that a trigger fired and
        not whether it should have.
        """
        ...

    async def save_firings(self, rows: list[dict[str, Any]]) -> None:
        """Insert trigger rows. Every one names its forecast and the action taken."""
        ...


class ModelCall(Protocol):
    """One model call: a prompt in, text out.

    This narrow because both places this agent uses a model want exactly this, and because
    a port that exposed the client would make every degraded-path test construct one.
    """

    async def __call__(self, prompt: str) -> str: ...
