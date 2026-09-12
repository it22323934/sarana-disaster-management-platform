"""DMC routes: situation reports, safety locations, occupancy, evacuation orders.

`POST /shelters/{id}/occupancy` is the only write in this service that changes what a later
read returns. A counted headcount overrides the modelled curve for that location from then
on, because a real count beats a model — that is the entire reason the write exists.

It is idempotent on `(location_id, counted_at)`. Sending the same count twice is the same
count, which is what makes it safe to retry after a timeout. Sending an *older* count than
the one already recorded is refused rather than applied: counts arrive out of order over a
bad link, and letting a stale one win would empty a shelter that is filling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import SimulatedHoursDep, StateDep, mock_json
from gov_mock.data import dmc as dmc_data
from gov_mock.data.districts import BY_CODE
from gov_mock.state import MockState, OccupancyCount

router = APIRouter(prefix="/dmc/v1", tags=["dmc"])


class OccupancyIn(BaseModel):
    """A headcount taken at one safety location."""

    model_config = ConfigDict(extra="forbid")

    occupancy: int = Field(ge=0)
    counted_at: datetime


def _occupancy_now(state: MockState, location: dmc_data.SafetyLocation, hours: float) -> int:
    """The occupancy to report: a real count if one was taken, else the model."""
    counted = state.occupancy_counts.get(location.location_id)
    if counted is not None:
        return counted.occupancy
    return dmc_data.modelled_occupancy(location, hours_since_landfall=hours, seed=state.seed)


def _location_body(state: MockState, location: dmc_data.SafetyLocation, hours: float) -> Any:
    counted = state.occupancy_counts.get(location.location_id)
    return {
        "location_id": location.location_id,
        "name": location.name,
        "district_code": location.district_code,
        "ds_division_code": location.ds_division_code,
        "lon": location.lon,
        "lat": location.lat,
        "capacity_persons": location.capacity_persons,
        "current_occupancy": _occupancy_now(state, location, hours),
        "facilities": list(location.facilities),
        "counted_at": counted.counted_at.isoformat() if counted else None,
    }


@router.get("/situation-reports", summary="DMC situation reports")
def situation_reports(
    state: StateDep,
    hours: SimulatedHoursDep,
    from_: str | None = Query(default=None, alias="from"),
) -> Any:
    """Situation reports issued up to the current simulated hour, newest first."""
    displaced = sum(
        _occupancy_now(state, location, hours)
        for location in state.locations
        if location.district_code in dmc_data.AFFECTED_DISTRICTS
    )
    reports = dmc_data.situation_reports(
        landfall_at=state.clock.landfall_at,
        hours_since_landfall=hours,
        displaced_now=displaced,
        seed=state.seed,
    )

    if from_ is not None:
        try:
            since = datetime.fromisoformat(from_)
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail="`from` must be an ISO 8601 instant"
            ) from error
        reports = [report for report in reports if report.issued_at >= since]

    return mock_json(
        {
            "situation_reports": [
                {
                    "report_id": report.report_id,
                    "issued_at": report.issued_at.isoformat(),
                    "hazard": report.hazard,
                    "districts_affected": list(report.districts_affected),
                    "persons_affected": report.persons_affected,
                    "persons_displaced": report.persons_displaced,
                    "deaths": report.deaths,
                    "injured": report.injured,
                    "summary": report.summary,
                }
                for report in reports
            ]
        }
    )


@router.get("/shelters", summary="Safety locations and their occupancy")
def shelters(
    state: StateDep,
    hours: SimulatedHoursDep,
    district: str | None = Query(default=None, description="District code, e.g. LK-51"),
) -> Any:
    """Safety locations, optionally narrowed to one district."""
    locations = state.locations
    if district is not None:
        if district not in BY_CODE:
            raise HTTPException(status_code=404, detail="No such district")
        locations = [entry for entry in locations if entry.district_code == district]

    return mock_json(
        {"shelters": [_location_body(state, location, hours) for location in locations]}
    )


@router.post("/shelters/{location_id}/occupancy", summary="Report a headcount")
def update_occupancy(location_id: str, payload: OccupancyIn, state: StateDep) -> Any:
    """Record a real headcount at one safety location.

    Idempotent on `(location_id, counted_at)`. An out-of-order count — one taken earlier
    than the count already held — is accepted by the API and *not* applied, and the
    response says so. Refusing it outright would make a field app retry forever; applying
    it would empty a shelter that is still filling.
    """
    location = state.locations_by_id.get(location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="No such safety location")

    existing = state.occupancy_counts.get(location_id)
    accepted = existing is None or payload.counted_at >= existing.counted_at

    if accepted:
        state.occupancy_counts[location_id] = OccupancyCount(
            location_id=location_id,
            occupancy=payload.occupancy,
            counted_at=payload.counted_at,
        )

    # Report what is held, not what was sent. For a refused out-of-order count these
    # differ, and a field app needs to see the count that actually stands.
    held = state.occupancy_counts[location_id]
    return mock_json(
        {
            "occupancy": {
                "location_id": location_id,
                "current_occupancy": held.occupancy,
                "counted_at": held.counted_at.isoformat(),
                "accepted": accepted,
            }
        }
    )


@router.get("/evacuation-orders", summary="Evacuation orders in force")
def evacuation_orders(state: StateDep, hours: SimulatedHoursDep) -> Any:
    """Evacuation orders currently in force."""
    orders = dmc_data.evacuation_orders(
        landfall_at=state.clock.landfall_at, hours_since_landfall=hours
    )
    return mock_json(
        {
            "evacuation_orders": [
                {
                    "order_id": order.order_id,
                    "issued_at": order.issued_at.isoformat(),
                    "effective_from": order.effective_from.isoformat(),
                    "ds_division_codes": list(order.ds_division_codes),
                    "reason": order.reason,
                    "issued_by": order.issued_by,
                }
                for order in orders
            ]
        }
    )
