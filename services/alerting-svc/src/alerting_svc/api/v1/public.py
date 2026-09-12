"""The alert history the public dashboard shows. No authentication.

`/alerts/feed.atom` and `/alerts/{id}/cap.xml` were already anonymous - a warning only
authenticated users can read is not a warning - but both are machine formats. This is the
same information in the shape a page renders: trilingual headline, description and
instruction, the CAP severity triple, the area size, and how many of the targeted contacts
the transport confirmed.

Two things it publishes that a warning system usually does not, and both are deliberate:

**Cancelled alerts stay in the history.** An alert that went out and was withdrawn is a
fact about what people were told. A history that drops its own retractions is not a
history, and the retraction is the part a journalist is looking for.

**The delivery shortfall is a field, not a footnote.** `targeted` and `reached` come back
together, so a page cannot show one without the other. An alert dispatched to 12,000
contacts and confirmed to 4,000 is the single most important number about that alert, and
`reached` alone would read as a success.

Nothing here can identify anybody. The counts are over contact hashes, the areas are
counts of GN divisions rather than a list, and no household, number or coordinate appears
in the query at all.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from alerting_svc.api.deps import PublicSessionDep
from alerting_svc.repo import queries
from sarana_shared.domain.time import utc_now

router = APIRouter(prefix="/public", tags=["public"])


class PublicAlert(BaseModel):
    """One alert as the world sees it.

    The three text fields are the full `LocalisedText`, not the caller's locale. The
    dashboard renders in three scripts from one cached response, and a per-locale endpoint
    would be three cache entries of the same alert that could drift apart.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    cap_identifier: str
    headline: dict[str, str]
    description: dict[str, str]
    instruction: dict[str, str]
    severity: str
    urgency: str
    certainty: str
    status: str = Field(description="DISPATCHED, or CANCELLED if it was later withdrawn.")
    effective_at: str
    expires_at: str
    active: bool = Field(
        description="Dispatched, not cancelled, and inside its effective window right now. "
        "Computed against the response's own `as_of` so a reader cannot see a list where "
        "one alert was judged active at a different instant from its neighbour."
    )
    gn_division_count: int
    targeted: int = Field(
        description="Contacts the dispatch aimed at, including households with no channel "
        "at all - they are the people who need a vehicle with a loudhailer, and dropping "
        "them would report an area as fully covered when a sixth of it cannot be reached."
    )
    reached: int = Field(
        description="Contacts the transport confirmed. Never higher than `targeted`, and "
        "the gap between the two is the figure that matters."
    )
    cap_xml_url: str = Field(description="The CAP 1.2 document. Also anonymous.")


class PublicAlertsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    alerts: list[PublicAlert]
    active_count: int
    as_of: str
    note: str


NOTE: Final = (
    "Alerts that were actually dispatched, and alerts that were dispatched and later "
    "cancelled. Drafts and alerts awaiting a human sign-off are never published: acting on "
    "an unapproved life-safety message is the harm the sign-off gate exists to prevent. "
    "Delivery is simulated in this phase - see /methodology."
)


@router.get("/alerts", response_model=PublicAlertsResponse)
async def public_alerts(
    session: PublicSessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Public alert history, newest first, with the currently active ones marked."""
    now = utc_now()
    rows = await queries.public_alerts(session, limit=limit, offset=offset)

    alerts = []
    for row in rows:
        effective = row["effective_at"]
        expires = row["expires_at"]
        active = row["status"] == "DISPATCHED" and effective <= now < expires
        alerts.append(
            {
                "id": row["id"],
                "cap_identifier": row["cap_identifier"],
                "headline": row["headline"],
                "description": row["description"],
                "instruction": row["instruction"],
                "severity": row["severity"],
                "urgency": row["urgency"],
                "certainty": row["certainty"],
                "status": row["status"],
                "effective_at": effective.isoformat(),
                "expires_at": expires.isoformat(),
                "active": active,
                "gn_division_count": int(row["gn_division_count"] or 0),
                "targeted": int(row["targeted"] or 0),
                "reached": int(row["reached"] or 0),
                "cap_xml_url": f"/api/v1/alerts/{row['id']}/cap.xml",
            }
        )

    return {
        "alerts": alerts,
        "active_count": sum(1 for alert in alerts if alert["active"]),
        "as_of": now.isoformat(),
        "note": NOTE,
    }
