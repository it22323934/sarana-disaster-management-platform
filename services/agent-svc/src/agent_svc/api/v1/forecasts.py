"""Impact forecasts and the anticipatory triggers hanging off them.

`hazard.impact_forecast` has existed since file 04 and `hazard.anticipatory_trigger`
beside it, and nothing exposed either. That single absence is what left `/ops/forecast`
rendering a "not built" screen: the forecast agent writes both tables, and the console had
no way to read what it wrote.

Read-only, for the same reason `hazard-events` is. A forecast is a derived record whose
unique key includes `generated_at` - a new run writes a new row and nothing updates one -
and a console that could write one would let an operator assert an impact class no model
produced.

**Latest per division, not every run.** The table keeps the whole forecast history so the
Learn loop can score accuracy after the event, but a screen showing six runs per division
would bury the current picture under its own audit trail. `DISTINCT ON` takes the most
recent per division; `GET /impact-forecasts/history` serves the rest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope

router = APIRouter(tags=["forecasts"])

# `forecast:read`, which every operational role holds. The forecast is what an operator
# acts on before anything has happened, so gating it behind an agent scope would hide the
# anticipatory half of the platform from the people it exists for.
ReadPrincipal = Depends(require(Scope.FORECAST_READ))

# One row per division: the most recent run.
_LATEST_FORECASTS = """
SELECT DISTINCT ON (f.gn_division_code)
       f.id::text, f.hazard_event_id::text, f.gn_division_id::text, f.gn_division_code,
       f.generated_at, f.valid_from, f.valid_to, f.impact_class, f.confidence,
       f.lead_time_hours, f.method, f.model_version, f.drivers,
       f.expected_households_affected, f.expected_road_access_loss, f.correlation_id
FROM hazard.impact_forecast f
WHERE (CAST(:hazard_event_id AS uuid) IS NULL
       OR f.hazard_event_id = CAST(:hazard_event_id AS uuid))
  AND (CAST(:gn AS text) IS NULL OR f.gn_division_code = CAST(:gn AS text))
  AND f.impact_class >= :min_class
ORDER BY f.gn_division_code, f.generated_at DESC
"""

# Every run for one division, newest first. This is the shape the Learn loop's accuracy
# question needs: what did we say, when did we say it, and how far ahead.
_FORECAST_HISTORY = """
SELECT f.id::text, f.hazard_event_id::text, f.gn_division_id::text, f.gn_division_code,
       f.generated_at, f.valid_from, f.valid_to, f.impact_class, f.confidence,
       f.lead_time_hours, f.method, f.model_version, f.drivers,
       f.expected_households_affected, f.expected_road_access_loss, f.correlation_id
FROM hazard.impact_forecast f
WHERE f.gn_division_code = :gn
  AND (CAST(:hazard_event_id AS uuid) IS NULL
       OR f.hazard_event_id = CAST(:hazard_event_id AS uuid))
ORDER BY f.generated_at DESC
LIMIT :limit
"""

# Fired triggers first, then the ones still armed. A trigger that has fired is a thing
# that happened and somebody has to know what it did; an armed one is a condition to watch.
_TRIGGERS = """
SELECT t.id::text, t.hazard_event_id::text, t.gn_division_code, t.condition,
       t.fired_at, t.action_taken, t.forecast_id::text, t.notes, t.created_at
FROM hazard.anticipatory_trigger t
WHERE (CAST(:hazard_event_id AS uuid) IS NULL
       OR t.hazard_event_id = CAST(:hazard_event_id AS uuid))
ORDER BY t.fired_at DESC NULLS LAST, t.created_at DESC
LIMIT :limit
"""


class ImpactForecastOut(BaseModel):
    """One division's forecast impact, and what moved it there.

    `drivers` is required non-empty by a CHECK constraint on the table, and it is the
    reason this endpoint is worth having. "150mm of rain" is a meteorological fact; "these
    40 divisions, this many households, this likely loss of road access, because the
    catchment is already at capacity" is a decision. The console renders every driver key
    it is given rather than a known subset, because the driver it does not know about is
    the one the model added.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    hazard_event_id: str
    gn_division_id: str
    gn_division_code: str
    generated_at: datetime
    valid_from: datetime
    valid_to: datetime
    impact_class: int = Field(description="0 none, 1 minor, 2 moderate, 3 major, 4 severe")
    confidence: float
    lead_time_hours: int
    method: str = Field(description="RULE_THRESHOLD or MODEL. Never both for one row.")
    model_version: str | None = None
    drivers: dict[str, Any]
    expected_households_affected: int
    expected_road_access_loss: bool
    correlation_id: str


class AnticipatoryTriggerOut(BaseModel):
    """A pre-agreed condition, and what happened when it fired.

    `condition` is stored as data rather than as code so it can be published and argued
    about in the quiet years, which is the only time that argument is useful. A trigger
    with `fired_at` set always has an `action_taken` - a CHECK enforces it - so a fired
    trigger that did nothing says `NO_ACTION` rather than leaving the question open.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    hazard_event_id: str
    gn_division_code: str | None = None
    condition: dict[str, Any]
    fired_at: datetime | None = None
    action_taken: str | None = None
    forecast_id: str | None = None
    notes: str | None = None
    created_at: datetime


@router.get("/impact-forecasts", response_model=list[ImpactForecastOut])
async def list_forecasts(
    request: Request,
    principal: Principal = ReadPrincipal,
    hazard_event_id: UUID | None = Query(default=None),
    gn_division_code: str | None = Query(default=None, max_length=16),
    min_impact_class: int = Query(
        default=0,
        ge=0,
        le=4,
        description="Filter server-side. Class 0 rows are most of the country on most days.",
    ),
    limit: int = Query(default=500, ge=1, le=2000),
) -> Any:
    """The current forecast per division, worst first.

    Ordered by what the operator has to act on first - the worst impact class, then the
    most households inside it - rather than by division code, because a screen ordered by
    code is a screen that has to be read in full.

    Sorted in Python rather than in SQL because `DISTINCT ON` has to order by its distinct
    key first. Cheap: this is one row per division that has a forecast, not one per
    division in the country.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            text(_LATEST_FORECASTS),
            {
                "hazard_event_id": hazard_event_id,
                "gn": gn_division_code,
                "min_class": min_impact_class,
            },
        )
        rows = [dict(row) for row in result.mappings()]

    rows.sort(
        key=lambda row: (
            -row["impact_class"],
            -row["expected_households_affected"],
            row["gn_division_code"],
        )
    )
    return rows[:limit]


@router.get("/impact-forecasts/history", response_model=list[ImpactForecastOut])
async def forecast_history(
    request: Request,
    gn_division_code: str = Query(max_length=16),
    principal: Principal = ReadPrincipal,
    hazard_event_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """Every run for one division, newest first.

    This is what makes a forecast reviewable after the event: the sequence of what was
    said and how far ahead it was said. A screen showing only the latest run cannot answer
    "did we see this coming", which is the question asked afterwards every time.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            text(_FORECAST_HISTORY),
            {"gn": gn_division_code, "hazard_event_id": hazard_event_id, "limit": limit},
        )
        return [dict(row) for row in result.mappings()]


@router.get("/anticipatory-triggers", response_model=list[AnticipatoryTriggerOut])
async def list_triggers(
    request: Request,
    principal: Principal = ReadPrincipal,
    hazard_event_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> Any:
    """Triggers for an event, fired ones first."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            text(_TRIGGERS), {"hazard_event_id": hazard_event_id, "limit": limit}
        )
        return [dict(row) for row in result.mappings()]
