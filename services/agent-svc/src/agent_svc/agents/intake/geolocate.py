"""Where a report is, and the one rule that matters: never invent a coordinate.

A model asked for a latitude and longitude will produce them. They will be well-formed, they
will be inside Sri Lanka, and they will be wrong in a way nothing downstream can detect - a
dispatch map shows a pin, a crew drives to it, and the household that reported is somewhere
else. There is no port in this agent through which a model can return a coordinate, and this
module is the reason.

Geocoding is a gazetteer lookup. Always.

## The precedence, and what each step costs when it is wrong

1. **Device GPS at 100 m or better** - used as given. This is the good case and most app
   reports are it.
2. **Device GPS worse than 100 m** - used, with the accuracy carried through so a map can
   draw the circle rather than the pin. A cell-derived fix five kilometres wide is still
   worth having; presenting it as a point is not.
3. **No GPS, one confident landmark match** - the landmark's centroid, a wide radius, and
   `location_source = inferred`. The source is what stops a dispatcher reading it as a
   measurement.
4. **No GPS, ambiguous or unmatched landmark** - the GN division and **no point at all**.
   This is the case people get wrong. A division-level incident is valid, dispatchable and
   honest; a point picked from three equally good matches is a guess wearing a coordinate's
   clothes.
5. Never a coordinate from a model.

## Division-level is a real answer

Sri Lanka has 14,022 GN divisions, so one is a small area - a village and its surroundings.
"Somewhere in this division" is enough to send a team, and it is what a radio dispatcher
worked from for decades. Treating it as a failure would push the pipeline toward inventing
precision it does not have, which is the failure this whole module is arranged to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

from agent_svc.agents.intake.ports import Gazetteer, Place, RawReport
from sarana_shared.domain.geo import PointSource, in_sri_lanka

_log = structlog.get_logger(__name__)

# At or below this, a device fix is good enough to use as a point without qualification.
# Build file 15 sets it; it is roughly the accuracy a phone reports with a clear sky.
GOOD_GPS_ACCURACY_M: Final = 100.0

# The radius a landmark centroid is presented with. Wide, because a village name locates a
# village and not a house, and a narrow radius on an inferred point is a false precision a
# dispatcher cannot see through.
LANDMARK_ACCURACY_M: Final = 2_000.0

# Confidence in the *location*, per source. Separate from the extraction's confidence: a
# report can be perfectly understood and imprecisely placed, and collapsing the two would
# hide which one a reviewer needs to fix.
CONFIDENCE_BY_SOURCE: Final[dict[str, float]] = {
    "gps_good": 0.95,
    "gps_coarse": 0.60,
    "landmark": 0.55,
    "division": 0.35,
    "unplaced": 0.0,
}


@dataclass(frozen=True, slots=True)
class Location:
    """Where a report is, how precisely, and how that was decided.

    `gn_division_code` is the field that always has a value when anything is known at all.
    The point is optional by design - see the module docstring.
    """

    gn_division_code: str | None
    lon: float | None = None
    lat: float | None = None
    accuracy_m: float | None = None
    source: str | None = None
    basis: str = ""
    confidence: float = 0.0

    @property
    def placed(self) -> bool:
        """Whether this report can be dispatched at all. A division is enough."""
        return self.gn_division_code is not None

    @property
    def has_point(self) -> bool:
        return self.lon is not None and self.lat is not None

    def as_sentence(self) -> str:
        if not self.placed:
            return "unplaced: no coordinate and no recognised landmark"
        if not self.has_point:
            return f"{self.gn_division_code} at division level, no point ({self.basis})"
        return (
            f"{self.gn_division_code} at {self.lat:.5f},{self.lon:.5f} "
            f"±{self.accuracy_m:.0f}m via {self.source} ({self.basis})"
        )


UNPLACED: Final = Location(gn_division_code=None, basis="nothing locatable in this report")


def _ambiguous(matches: list[Place]) -> bool:
    """Whether the best gazetteer match is clearly better than the next.

    Two places with the same name are the normal case in Sri Lanka, not an edge one. The
    gazetteer returns them best-first, so ambiguity is decided on whether the runner-up is
    close enough to be a real alternative - and matches in different divisions are the ones
    that matter, since two entries for one village in one division are the same place.
    """
    if len(matches) < 2:
        return False
    divisions = {match.gn_division_code for match in matches}
    return len(divisions) > 1


async def resolve(
    report: RawReport,
    *,
    landmarks: list[str],
    gazetteer: Gazetteer,
) -> Location:
    """Where this report is, by the precedence above.

    Returns `UNPLACED` rather than raising when nothing can be determined. An unplaced
    report is a real state that `incident_svc.service.intake` already handles - it stays in
    the queue, visible, and a human can place it from the text.
    """
    if report.has_coordinate:
        placed = await _from_coordinate(report, gazetteer)
        if placed is not None:
            return placed

    if landmarks:
        placed = await _from_landmarks(landmarks, gazetteer, near=report.sender_gn_division_code)
        if placed is not None:
            return placed

    if report.sender_gn_division_code:
        # Nothing in the report locates it, but the channel knows roughly where the sender
        # is. Division level, no point, and the basis says where it came from - a
        # dispatcher reading "the sender's registered division" treats it differently from
        # a landmark the report actually named.
        return Location(
            gn_division_code=report.sender_gn_division_code,
            source=PointSource.INFERRED.value,
            basis="the sender's known division; the report itself named no location",
            confidence=CONFIDENCE_BY_SOURCE["division"],
        )

    _log.info(
        "intake_report_unplaced",
        report_id=report.report_id,
        channel=report.channel,
        had_landmarks=bool(landmarks),
        impact="valid and queued, but not dispatchable until somebody places it",
    )
    return UNPLACED


async def _from_coordinate(report: RawReport, gazetteer: Gazetteer) -> Location | None:
    """Steps 1 and 2: a device fix, used as given, with its accuracy carried through."""
    lon, lat = report.lon, report.lat
    if lon is None or lat is None:
        return None

    if not in_sri_lanka(lon, lat):
        # Not dropped silently. A coordinate outside the country is either a client bug or
        # a report about somewhere this platform does not serve, and both are worth a line
        # in the log rather than a quiet fallback to the landmark path.
        _log.warning(
            "intake_coordinate_outside_sri_lanka",
            report_id=report.report_id,
            impact="the coordinate was not used; the report falls back to its landmarks",
        )
        return None

    division = await gazetteer.division_for(lon, lat)
    if division is None:
        return None

    accuracy = report.location_accuracy_m
    good = accuracy is not None and accuracy <= GOOD_GPS_ACCURACY_M
    return Location(
        gn_division_code=division,
        lon=lon,
        lat=lat,
        accuracy_m=accuracy,
        source=report.location_source or PointSource.GPS.value,
        basis=(
            "device fix within 100m"
            if good
            else f"device fix, {accuracy:.0f}m accuracy"
            if accuracy
            else "device fix, no accuracy"
        ),
        confidence=CONFIDENCE_BY_SOURCE["gps_good" if good else "gps_coarse"],
    )


async def _from_landmarks(
    landmarks: list[str], gazetteer: Gazetteer, *, near: str | None
) -> Location | None:
    """Steps 3 and 4: a gazetteer lookup, and a refusal to pick between equals."""
    for name in landmarks:
        matches = await gazetteer.lookup(name, near_division=near)
        if not matches:
            continue

        best = matches[0]
        if _ambiguous(matches):
            # The case this module exists for. Several divisions answer to this name, so
            # the division is as far as the evidence goes - and it is far enough to send
            # somebody.
            _log.info(
                "intake_landmark_ambiguous",
                landmark=name,
                divisions=sorted({match.gn_division_code for match in matches})[:5],
                impact="resolved to division level with no point rather than guessing one",
            )
            return Location(
                gn_division_code=best.gn_division_code,
                source=PointSource.INFERRED.value,
                basis=(
                    f"{name!r} matches {len(matches)} places in different divisions; "
                    "no point was assigned"
                ),
                confidence=CONFIDENCE_BY_SOURCE["division"],
            )

        return Location(
            gn_division_code=best.gn_division_code,
            lon=best.lon,
            lat=best.lat,
            accuracy_m=max(best.accuracy_m, LANDMARK_ACCURACY_M),
            source=PointSource.INFERRED.value,
            basis=f"landmark {name!r} matched {best.name} in the gazetteer",
            confidence=CONFIDENCE_BY_SOURCE["landmark"],
        )

    return None
