"""National Building Research Organisation — landslide bulletins, zonation, thresholds.

Two kinds of data with very different lifetimes:

  **Zonation is reference data.** A GN division's landslide hazard zone changes on a survey
  cycle, not during an event. Cache it hard.

  **Bulletins are event-driven.** NBRO issues early-warning bulletins by DS division during
  heavy rain, and they expire.

**About the thresholds.** `rain_thresholds()` returns the cumulative-rainfall figures the
rule-based fallback forecast keys off when no model is available. They are exposed as data
from this adapter, rather than living as constants inside agent code, for one reason: when
NBRO's real figures arrive they replace a served value, not a code change in an agent
nobody remembers keys off them.

The values the mock serves are **plausible, documented, and not official**. NBRO's
operational thresholds are not published in a machine-readable form this repository can
cite, and inventing a number that then reads as authoritative is how a warning gets issued
late. `ThresholdSet.provenance` says so on every record, and it must keep saying so until
somebody has the real figures in writing.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class LandslideZone(IntEnum):
    """NBRO's four-level landslide hazard zonation.

    Higher is more hazardous. Matches `admin.gn_division.landslide_zone` in the SARANA
    schema, which is populated from this zonation.
    """

    LOW = 1
    MODERATE = 2
    HIGH = 3
    VERY_HIGH = 4


class ZonationRecord(BaseModel):
    """The hazard zone for one GN division."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gn_division_code: str
    zone: LandslideZone
    surveyed_year: int


class NbroBulletin(BaseModel):
    """One landslide early-warning bulletin, issued against DS divisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bulletin_id: str
    level: str
    issued_at: datetime
    valid_until: datetime
    ds_division_codes: tuple[str, ...] = Field(default_factory=tuple)
    advice: str


class ThresholdSet(BaseModel):
    """The cumulative-rainfall thresholds for one hazard zone.

    Three levels, in millimetres of rain accumulated over the stated window. A reading at
    or above `watch_mm` puts the zone on watch; `warning_mm` and `evacuate_mm` escalate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    zone: LandslideZone
    window_hours: int
    watch_mm: float
    warning_mm: float
    evacuate_mm: float
    # Carried on every record, not in a README. Whoever reads a threshold at 3 a.m. sees
    # where it came from in the same breath as the number.
    provenance: str

    @property
    def is_official(self) -> bool:
        """Whether these figures came from NBRO rather than the mock's stand-ins."""
        return not self.provenance.startswith("SYNTHETIC")


class NbroClient(Protocol):
    """What SARANA needs from NBRO."""

    async def bulletins(self, *, ds_division_code: str | None = None) -> list[NbroBulletin]:
        """Bulletins currently in force, optionally for one DS division."""
        ...

    async def zonation(self, *, gn_division_code: str) -> ZonationRecord:
        """The landslide hazard zone for one GN division.

        Raises:
            GovRecordNotFound: if the division is not in the zonation survey.
        """
        ...

    async def rain_thresholds(self) -> list[ThresholdSet]:
        """The cumulative-rainfall thresholds, one set per hazard zone."""
        ...

    async def aclose(self) -> None: ...


class NbroMockClient(MockGovClient):
    """Talks to `gov-mock`'s NBRO routes."""

    system: ClassVar[str] = "nbro"

    async def bulletins(self, *, ds_division_code: str | None = None) -> list[NbroBulletin]:
        body = await self._get_json(
            "/nbro/v1/bulletins", params={"ds_division_id": ds_division_code}
        )
        return [NbroBulletin.model_validate(row) for row in body["bulletins"]]

    async def zonation(self, *, gn_division_code: str) -> ZonationRecord:
        body = await self._get_json(
            "/nbro/v1/zonation", params={"gn_division_id": gn_division_code}
        )
        return ZonationRecord.model_validate(body["zonation"])

    async def rain_thresholds(self) -> list[ThresholdSet]:
        body = await self._get_json("/nbro/v1/rain-thresholds")
        return [ThresholdSet.model_validate(row) for row in body["thresholds"]]


class NbroRealClient(RealClientStub):
    """NBRO's landslide early-warning feed. Not yet written.

    NBRO issues bulletins by press release and to the DMC directly. There is no public
    machine-readable feed, so this integration is a genuine negotiation rather than a key
    request — and the zonation data behind it is a survey product that is licensed, not
    given away.

    Getting the real `rain_thresholds` in writing is the single highest-value item on this
    list. Until then the fallback forecast is running on stand-in numbers, which
    `ThresholdSet.is_official` reports as False everywhere it is used.
    """

    integration: ClassVar[Integration] = Integration(
        system="nbro",
        organisation="National Building Research Organisation",
        base_url="https://api.nbro.gov.lk",
        credential="a client certificate issued to the DMC, plus a per-district data licence",
        agreement=(
            "a data-sharing agreement covering the landslide zonation survey (licensed "
            "product) and written confirmation of the operational rainfall thresholds"
        ),
    )

    async def bulletins(self, *, ds_division_code: str | None = None) -> list[NbroBulletin]:
        self._pending("bulletins", "/bulletins")

    async def zonation(self, *, gn_division_code: str) -> ZonationRecord:
        self._pending("zonation", "/zonation")

    async def rain_thresholds(self) -> list[ThresholdSet]:
        self._pending("rain_thresholds", "/rain-thresholds")
