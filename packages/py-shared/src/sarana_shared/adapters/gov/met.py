"""Department of Meteorology — warnings, observations and rainfall forecast.

The hazard feed the Forecast and Impact agent (file 13) keys off. Two things about it are
worth knowing before writing anything against it:

**It is XML.** Not a JSON API with an XML option — the warnings feed is XML, because that
is what the Department publishes. The adapter parses it into typed records so nothing
above this layer has to know that.

**Rainfall is the input to a life-safety decision.** An observation carries the station it
came from and the instant it was taken, and neither is optional. A rainfall figure without
a timestamp cannot be compared against a cumulative threshold, and a threshold comparison
is what triggers a landslide warning.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import (
    Integration,
    MockGovClient,
    RealClientStub,
    parse_xml,
    require_mock_xml,
)


class WarningLevel(StrEnum):
    """The Department's three-level warning scale.

    Not mapped onto CAP severity here. The mapping is a judgement the Warning agent makes
    with a human in the loop, and burying it in a transport adapter would hide the one
    decision in this path that somebody has to be accountable for.
    """

    YELLOW = "Yellow"
    AMBER = "Amber"
    RED = "Red"


class MetWarning(BaseModel):
    """One warning bulletin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warning_id: str
    level: WarningLevel
    hazard: str
    headline: str
    issued_at: datetime
    valid_until: datetime
    district_codes: tuple[str, ...] = Field(default_factory=tuple)


class RainfallObservation(BaseModel):
    """One station reading.

    `rainfall_mm_24h` is the rolling 24-hour accumulation, which is what the NBRO
    thresholds are expressed in. Instantaneous intensity is a different number and mixing
    the two silently would move every landslide trigger.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str
    station_name: str
    district_code: str
    lon: float
    lat: float
    observed_at: datetime
    rainfall_mm_24h: float
    # Stations go offline in exactly the weather that matters. A gap is reported as a gap.
    reporting: bool = True


class RainfallForecast(BaseModel):
    """Expected rainfall over a forward window, for one district."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    district_code: str
    hours: int
    expected_mm: float
    # The Department publishes a confidence band; a point forecast presented without one
    # invites a decision it cannot support.
    confidence_low_mm: float
    confidence_high_mm: float
    issued_at: datetime


class MetClient(Protocol):
    """What SARANA needs from the Department of Meteorology."""

    async def warnings(self) -> list[MetWarning]:
        """Every warning currently in force."""
        ...

    async def warning(self, warning_id: str) -> MetWarning:
        """One warning by id.

        Raises:
            GovRecordNotFound: if no such warning exists.
        """
        ...

    async def observations(
        self,
        *,
        station: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RainfallObservation]:
        """Station readings, optionally narrowed to one station and a window."""
        ...

    async def rainfall_forecast(self, *, district_code: str, hours: int) -> RainfallForecast:
        """Expected rainfall for a district over the next `hours`."""
        ...

    async def aclose(self) -> None: ...


class MetMockClient(MockGovClient):
    """Talks to `gov-mock`'s Met Department routes."""

    system: ClassVar[str] = "met"

    async def warnings(self) -> list[MetWarning]:
        document = await self._get_text("/met/v1/warnings")
        root = require_mock_xml(parse_xml(document, system=self.system), system=self.system)
        return [_warning_from_xml(element) for element in root.findall("warning")]

    async def warning(self, warning_id: str) -> MetWarning:
        document = await self._get_text(f"/met/v1/warnings/{warning_id}")
        root = require_mock_xml(parse_xml(document, system=self.system), system=self.system)
        return _warning_from_xml(root if root.tag == "warning" else _first_warning(root))

    async def observations(
        self,
        *,
        station: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RainfallObservation]:
        body = await self._get_json(
            "/met/v1/observations",
            params={
                "station": station,
                "from": since.isoformat() if since else None,
                "to": until.isoformat() if until else None,
            },
        )
        return [RainfallObservation.model_validate(row) for row in body["observations"]]

    async def rainfall_forecast(self, *, district_code: str, hours: int) -> RainfallForecast:
        body = await self._get_json(
            "/met/v1/forecast/rainfall",
            params={"district": district_code, "hours": hours},
        )
        return RainfallForecast.model_validate(body["forecast"])


class MetRealClient(RealClientStub):
    """The Department of Meteorology's public feed. Not yet written.

    The Department publishes warnings at `meteo.gov.lk`; a machine-readable feed for
    third parties is a separate arrangement and is what the integration below describes.
    Do not scrape the public site: a warning parsed out of a rendered page is a warning
    that silently stops arriving the day somebody changes a CSS class.
    """

    integration: ClassVar[Integration] = Integration(
        system="met",
        organisation="Department of Meteorology, Sri Lanka",
        base_url="https://api.meteo.gov.lk",
        credential="a named API key issued to DMC/SARANA, with an agreed request ceiling",
        agreement=(
            "an MoU covering redistribution of warnings to citizens, since SARANA "
            "re-publishes them as CAP rather than consuming them internally"
        ),
    )

    async def warnings(self) -> list[MetWarning]:
        self._pending("warnings", "/warnings")

    async def warning(self, warning_id: str) -> MetWarning:
        self._pending("warning", f"/warnings/{warning_id}")

    async def observations(
        self,
        *,
        station: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RainfallObservation]:
        self._pending("observations", "/observations")

    async def rainfall_forecast(self, *, district_code: str, hours: int) -> RainfallForecast:
        self._pending("rainfall_forecast", "/forecast/rainfall")


def _first_warning(root: Any) -> Any:
    """The single warning inside a wrapper element, for the by-id route."""
    found = root.find("warning")
    return found if found is not None else root


def _warning_from_xml(element: Any) -> MetWarning:
    """Build a warning from its XML element.

    Missing text is `""` rather than `None` so pydantic reports which field is wrong
    against the real value, instead of every absent field looking identical.
    """
    districts = element.find("districts")
    codes = (
        tuple(child.text or "" for child in districts.findall("district"))
        if districts is not None
        else ()
    )
    return MetWarning(
        warning_id=_text(element, "id"),
        level=WarningLevel(_text(element, "level")),
        hazard=_text(element, "hazard"),
        headline=_text(element, "headline"),
        issued_at=datetime.fromisoformat(_text(element, "issuedAt")),
        valid_until=datetime.fromisoformat(_text(element, "validUntil")),
        district_codes=codes,
    )


def _text(element: Any, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "") if child is not None else ""
