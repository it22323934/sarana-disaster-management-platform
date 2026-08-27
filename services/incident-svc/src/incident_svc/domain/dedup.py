"""Deterministic duplicate detection, used when semantic matching is unavailable.

The rule from the build brief: same GN division, same incident type, within 300 metres,
within 20 minutes.

**Candidates are flagged, never auto-merged.** That is the whole design. A false merge
hides a second emergency behind the first one and nobody goes to it - the two reports look
like one household, one team is sent, and the other family waits for someone who is never
coming. A false split costs a dispatcher ten seconds.

So this returns candidates for a human, and the merge endpoint requires a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sarana_shared.domain.geo import haversine_m

# Two reports of the same thing from one village arrive from different phones with GPS
# fixes tens of metres apart. 300m is wide enough to catch that and narrow enough not to
# join two streets.
PROXIMITY_METRES: Final = 300.0

# Long enough to cover a household reporting twice while waiting, short enough that a
# second, genuinely new emergency in the same place is not swallowed by the first.
WINDOW_MINUTES: Final = 20

METHOD: Final = "rule-v1"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One report or incident that might be the same event as another."""

    id: str
    gn_division_code: str
    incident_type: str
    lon: float | None
    lat: float | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """A flagged pair, with the reason a human can check."""

    existing_id: str
    distance_m: float | None
    minutes_apart: float
    method: str = METHOD

    @property
    def reason(self) -> str:
        distance = "unknown distance" if self.distance_m is None else f"{self.distance_m:.0f}m"
        return (
            f"same division and type, {distance} apart, "
            f"{self.minutes_apart:.0f} minutes apart ({self.method})"
        )


def _distance_between(left: Candidate, right: Candidate) -> float | None:
    """Metres apart, or None when either has no location.

    A missing location does not disqualify a pair. Reports arriving by SMS often have no
    coordinates at all, and those are exactly the ones most likely to be duplicates of an
    app report from the same household.
    """
    if left.lon is None or left.lat is None or right.lon is None or right.lat is None:
        return None
    return haversine_m(left.lon, left.lat, right.lon, right.lat)


def is_candidate(incoming: Candidate, existing: Candidate) -> DuplicateCandidate | None:
    """Whether two reports might be the same event.

    All four conditions must hold. Division and type are exact; distance is skipped when
    either side lacks a location rather than being treated as infinite.
    """
    if incoming.gn_division_code != existing.gn_division_code:
        return None
    if incoming.incident_type.upper() != existing.incident_type.upper():
        return None

    apart = abs((incoming.occurred_at - existing.occurred_at).total_seconds()) / 60.0
    if apart > WINDOW_MINUTES:
        return None

    distance = _distance_between(incoming, existing)
    if distance is not None and distance > PROXIMITY_METRES:
        return None

    return DuplicateCandidate(
        existing_id=existing.id, distance_m=distance, minutes_apart=apart
    )


def find_candidates(
    incoming: Candidate, existing: list[Candidate]
) -> list[DuplicateCandidate]:
    """Every plausible duplicate, closest in time first.

    Returns all of them rather than only the best. A dispatcher deciding whether to merge
    wants to see the cluster, not one arbitrary member of it.
    """
    found = [
        candidate
        for other in existing
        if other.id != incoming.id and (candidate := is_candidate(incoming, other))
    ]
    return sorted(found, key=lambda candidate: candidate.minutes_apart)


def window_start(now: datetime) -> datetime:
    """The earliest time a candidate could have been reported.

    Used to bound the query rather than scanning every open incident.
    """
    return now - timedelta(minutes=WINDOW_MINUTES)
