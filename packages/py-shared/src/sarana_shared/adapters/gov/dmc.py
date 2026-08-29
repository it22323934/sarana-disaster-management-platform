"""Disaster Management Centre — situation reports, safety locations, evacuation orders.

The DMC is the national coordinating authority. SARANA reads from it and, for occupancy,
writes back to it; it is not a replacement for it.

`update_occupancy` is the only write on this adapter, and it is the one that matters
operationally: a shelter's occupancy is what tells a dispatcher whether there is anywhere
to send a family. It is idempotent on `(location_id, counted_at)` so a retry after a
timeout cannot double-count a village.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class SafetyLocation(BaseModel):
    """A place people are moved to.

    Called a "safety location" rather than a camp, following DMC usage: most are schools
    and temples that are only a shelter for the days they are needed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    location_id: str
    name: str
    district_code: str
    ds_division_code: str
    lon: float
    lat: float
    capacity_persons: int = Field(ge=0)
    current_occupancy: int = Field(ge=0)
    facilities: tuple[str, ...] = Field(default_factory=tuple)
    counted_at: datetime | None = None

    @property
    def spare_capacity(self) -> int:
        """Places still available. Never negative — over-occupancy reads as full.

        A shelter holding more people than its stated capacity is a real and common
        situation, and reporting it as negative spare capacity would let it be summed into
        a district total that claims room that does not exist.
        """
        return max(0, self.capacity_persons - self.current_occupancy)

    @property
    def is_over_capacity(self) -> bool:
        """Whether more people are here than the location is rated for."""
        return self.current_occupancy > self.capacity_persons


class SituationReport(BaseModel):
    """One DMC situation report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    issued_at: datetime
    hazard: str
    districts_affected: tuple[str, ...] = Field(default_factory=tuple)
    persons_affected: int = Field(ge=0)
    persons_displaced: int = Field(ge=0)
    deaths: int = Field(ge=0)
    injured: int = Field(ge=0)
    summary: str


class EvacuationOrder(BaseModel):
    """An order to evacuate, issued against DS divisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    issued_at: datetime
    effective_from: datetime
    ds_division_codes: tuple[str, ...] = Field(default_factory=tuple)
    reason: str
    # Who signed it. An evacuation order with no named authority is not one.
    issued_by: str


class OccupancyUpdate(BaseModel):
    """The DMC's acknowledgement of an occupancy write."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    location_id: str
    current_occupancy: int = Field(ge=0)
    counted_at: datetime
    accepted: bool


class DmcClient(Protocol):
    """What SARANA needs from the Disaster Management Centre."""

    async def situation_reports(self, *, since: datetime | None = None) -> list[SituationReport]:
        """Situation reports issued since an instant, newest first."""
        ...

    async def safety_locations(self, *, district_code: str | None = None) -> list[SafetyLocation]:
        """Safety locations, optionally narrowed to one district."""
        ...

    async def update_occupancy(
        self, *, location_id: str, occupancy: int, counted_at: datetime
    ) -> OccupancyUpdate:
        """Report a headcount at one safety location.

        Idempotent on `(location_id, counted_at)`: sending the same count twice is the
        same count, which is what makes it safe to retry after a timeout.
        """
        ...

    async def evacuation_orders(self) -> list[EvacuationOrder]:
        """Evacuation orders currently in force."""
        ...

    async def aclose(self) -> None: ...


class DmcMockClient(MockGovClient):
    """Talks to `gov-mock`'s DMC routes."""

    system: ClassVar[str] = "dmc"

    async def situation_reports(self, *, since: datetime | None = None) -> list[SituationReport]:
        body = await self._get_json(
            "/dmc/v1/situation-reports", params={"from": since.isoformat() if since else None}
        )
        return [SituationReport.model_validate(row) for row in body["situation_reports"]]

    async def safety_locations(self, *, district_code: str | None = None) -> list[SafetyLocation]:
        body = await self._get_json("/dmc/v1/shelters", params={"district": district_code})
        return [SafetyLocation.model_validate(row) for row in body["shelters"]]

    async def update_occupancy(
        self, *, location_id: str, occupancy: int, counted_at: datetime
    ) -> OccupancyUpdate:
        body = await self._post_json(
            f"/dmc/v1/shelters/{location_id}/occupancy",
            json={"occupancy": occupancy, "counted_at": counted_at.isoformat()},
        )
        return OccupancyUpdate.model_validate(body["occupancy"])

    async def evacuation_orders(self) -> list[EvacuationOrder]:
        body = await self._get_json("/dmc/v1/evacuation-orders")
        return [EvacuationOrder.model_validate(row) for row in body["evacuation_orders"]]


class DmcRealClient(RealClientStub):
    """The DMC's internal systems. Not yet written.

    The DMC publishes situation reports as PDFs and maintains safety-location lists in
    spreadsheets circulated by district. There is no API today, which makes this the
    integration most likely to start as a scheduled import rather than a live client —
    and the occupancy write the hardest to negotiate, because it is SARANA proposing to
    put numbers into the DMC's own record.
    """

    integration: ClassVar[Integration] = Integration(
        system="dmc",
        organisation="Disaster Management Centre",
        base_url="https://api.dmc.gov.lk",
        credential="an internal service account on the DMC network, VPN-reachable only",
        agreement=(
            "written authority for SARANA to write occupancy into the DMC record, "
            "naming which officers' counts are accepted and how a correction is made"
        ),
    )

    async def situation_reports(self, *, since: datetime | None = None) -> list[SituationReport]:
        self._pending("situation_reports", "/situation-reports")

    async def safety_locations(self, *, district_code: str | None = None) -> list[SafetyLocation]:
        self._pending("safety_locations", "/shelters")

    async def update_occupancy(
        self, *, location_id: str, occupancy: int, counted_at: datetime
    ) -> OccupancyUpdate:
        self._pending("update_occupancy", f"/shelters/{location_id}/occupancy")

    async def evacuation_orders(self) -> list[EvacuationOrder]:
        self._pending("evacuation_orders", "/evacuation-orders")
