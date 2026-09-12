"""Hazard events — the thing every disaster timeline is measured from.

One endpoint, and it exists because two surfaces cannot work without it:

  - **The alert composer.** `POST /alerts` requires a `hazard_event_id`, and until this
    existed nothing could supply one. An operator could compose and check a message and
    then had no way to name the event it was about.
  - **The time spine.** `landfall_at` is T+0. Every runbook, situation report and demo
    speaks in offsets from it — T-72h, T+14d — and a console with no access to it can only
    show wall-clock time, which is not how anybody working an incident talks.

Read-only, deliberately. A hazard event is declared by the forecast agent from a
meteorological feed or by DMC through the inbound path, and a console that could create one
would let an operator invent a cyclone. Closing one is a state transition with consequences
for every alert and incident hanging off it, and it belongs with the agent that owns the
lifecycle rather than behind a button.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope

router = APIRouter(prefix="/hazard-events", tags=["hazard-events"])

# `incident:read` rather than an agent scope. Everyone who works an incident needs to know
# which event they are working, including a GN officer who holds no agent scope at all.
ReadPrincipal = Depends(require(Scope.INCIDENT_READ))

# `open_only` excludes CLOSED rather than filtering by date, because an event stays open
# for as long as its recovery does — months, sometimes — and a date window would drop the
# one an operator is still working.
_LIST_EVENTS = """
SELECT id::text, type, name, source, source_ref, declared_at, landfall_at, status
FROM hazard.hazard_event
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (NOT CAST(:open_only AS boolean) OR status <> 'CLOSED')
ORDER BY COALESCE(landfall_at, declared_at, created_at) DESC
LIMIT :limit
"""


class HazardEventOut(BaseModel):
    """One hazard event.

    `name` is trilingual and stays a mapping rather than being resolved here: the console
    picks the locale, and a server that chose one would have to know the reader's language
    from a header that is only a hint.

    `landfall_at` is nullable and stays nullable. An event under monitoring has no landfall
    yet, and inventing one — the declaration time, say — would put a fabricated T+0 on
    every situation report generated from it.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    name: dict[str, str]
    source: str
    source_ref: str
    declared_at: datetime | None
    landfall_at: datetime | None
    status: str


@router.get("", response_model=list[HazardEventOut])
async def list_hazard_events(
    request: Request,
    principal: Principal = ReadPrincipal,
    status: str | None = Query(default=None, max_length=16),
    open_only: bool = Query(
        default=True, description="Exclude closed events. The console's default."
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """Hazard events, most recent landfall first.

    Ordered by landfall rather than by creation, because that is the order an operator
    thinks in: the event that made landfall this morning is the one they are working, even
    if a monitoring record for next week's depression was created after it.
    `COALESCE` falls back to the declaration and then the row's own creation, so an event
    with no landfall yet still sorts sensibly rather than sinking to the bottom.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            text(_LIST_EVENTS),
            {"status": status, "open_only": open_only, "limit": limit},
        )
        return [dict(row) for row in result.mappings()]
