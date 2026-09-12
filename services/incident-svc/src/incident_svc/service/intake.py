"""Turning a `ReportIntake` into a stored report and an incident.

One path, whichever channel the report arrived on. The steps are ordered so that the
report is durable before anything that can fail is attempted:

  1. Store the raw report. Nothing after this can lose it.
  2. Resolve its division. May fail; the report stays.
  3. Look for duplicates. Flags, never merges.
  4. Create or link an incident.
  5. Score it. Rule-based unless assisted triage is available.
  6. Enqueue the event in the same transaction as the write.

Step 1 first is the whole design. Every later step is an enrichment, and an enrichment
that fails must degrade the record rather than reject it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from incident_svc.adapters.channels.intake import ReportIntake
from incident_svc.adapters.core_api import CoreApiClient
from incident_svc.domain import dedup, triage
from incident_svc.repo import OutboxEvent, queries
from sarana_shared.domain.geo import GeoPoint, PointSource
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.events import catalogue
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.outbox import enqueue

_log = structlog.get_logger(__name__)

SERVICE = "incident-svc"

# Where an unplaceable report goes. A real division code would be a lie; this one sorts
# to the top of any list of divisions, which is the point - it should be visible.
UNPLACED_DIVISION_CODE = "UNPLACED"


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """What one report produced."""

    report_id: str
    incident_id: str | None
    public_ref: str | None
    duplicate_candidates: list[dict[str, Any]]
    assisted: bool
    placed: bool

    @property
    def flagged_duplicate(self) -> bool:
        return bool(self.duplicate_candidates)


def _trusted_point(intake: ReportIntake) -> GeoPoint | None:
    """The report's coordinate, with provenance, or None.

    The schema refuses to store a point that carries no accuracy: "a point with no
    accuracy is not trusted for dispatch, so it may not exist". That is the right rule -
    a bare coordinate looks authoritative on a map and may be a cell-tower guess five
    kilometres wide.

    So a missing accuracy is filled in from the source's documented floor rather than
    invented, and a coordinate with no source at all is dropped. The report itself always
    survives: losing the point costs a dispatcher one lookup, losing the report costs
    somebody their emergency.
    """
    if intake.lon is None or intake.lat is None:
        return None

    raw_source = intake.location_source
    if raw_source is None:
        _log.info(
            "location_dropped_no_provenance",
            channel=intake.channel,
            reason="a coordinate with no source cannot be trusted for dispatch",
        )
        return None

    try:
        source = PointSource(raw_source)
    except ValueError:
        _log.warning("location_dropped_unknown_source", source=raw_source)
        return None

    try:
        return GeoPoint.from_source(
            lon=intake.lon,
            lat=intake.lat,
            source=source,
            accuracy_m=float(intake.location_accuracy_m)
            if intake.location_accuracy_m is not None
            else None,
        )
    except ValueError as error:
        # Outside Sri Lanka, or otherwise implausible. Keep the report, drop the point.
        _log.info("location_dropped_implausible", error=str(error))
        return None


# Crockford base32: no I, L, O or U. Those are the characters people mishear and
# mistranscribe, and this reference is read aloud over a radio and written on paper.
_REFERENCE_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _public_ref(now: datetime | None = None) -> str:
    """`INC-251128-K3M9PQ` - what a citizen is told and an operator says on the radio.

    The shape is fixed by a CHECK constraint, so it is built to match rather than being
    formatted freely: date first because an operator sorting a stack of paper wants that,
    then six random characters from an alphabet with no ambiguous letters.
    """
    moment = now or utc_now()
    raw = uuid7().int
    suffix = "".join(_REFERENCE_ALPHABET[(raw >> (shift * 5)) & 0x1F] for shift in range(6))
    return f"INC-{moment:%y%m%d}-{suffix}"


async def accept(
    session: AsyncSession,
    intake: ReportIntake,
    *,
    core_api: CoreApiClient,
    token: str | None = None,
    assisted: bool = False,
) -> IntakeResult:
    """Accept one report and place it in the queue.

    `assisted` says whether agent-assisted ranking produced the score. It is threaded
    through to the response rather than inferred, because the console must be able to tell
    a dispatcher which one they are looking at.
    """
    # 1. Durable first.
    point = _trusted_point(intake)

    report = await queries.insert_report(
        session,
        correlation_id=intake.correlation_id,
        channel=intake.channel,
        received_at=intake.received_at,
        sender_msisdn_hash=intake.sender_msisdn_hash,
        sender_household_id=None,
        raw_text=intake.raw_text,
        reported_language=intake.reported_language,
        lon=point.lon if point else None,
        lat=point.lat if point else None,
        location_accuracy_m=int(point.accuracy_m) if point else None,
        location_source=point.source.value if point else None,
        processing_status="RECEIVED",
    )
    report_id = UUID(report["id"])

    # 2. Place it, if we can.
    division = None
    if point is not None:
        division = await core_api.resolve(lon=point.lon, lat=point.lat, token=token)

    if division is None:
        _log.info(
            "report_unplaced",
            report_id=str(report_id),
            channel=intake.channel,
            had_location=point is not None,
        )
        await _enqueue_received(
            session, intake, report_id, placed=False, has_location=point is not None
        )
        return IntakeResult(
            report_id=report["id"],
            incident_id=None,
            public_ref=None,
            duplicate_candidates=[],
            assisted=assisted,
            placed=False,
        )

    incident_type = (intake.incident_type or "OTHER").upper()

    # 3. Flag duplicates. Never merge automatically.
    now = utc_now()
    existing = await queries.dedup_candidates(
        session,
        gn_division_code=division.gn_division_code,
        incident_type=incident_type,
        since=dedup.window_start(now),
    )
    candidates = dedup.find_candidates(
        dedup.Candidate(
            id=str(report_id),
            gn_division_code=division.gn_division_code,
            incident_type=incident_type,
            lon=point.lon if point else None,
            lat=point.lat if point else None,
            occurred_at=intake.received_at,
        ),
        [
            dedup.Candidate(
                id=row["id"],
                gn_division_code=row["gn_division_code"],
                incident_type=row["type"],
                lon=row["lon"],
                lat=row["lat"],
                occurred_at=row["first_reported_at"],
            )
            for row in existing
        ],
    )

    # 4. Link to the strongest candidate, or open a new incident.
    #
    # Linking is not merging: the incident stays as it is and gains a second report, which
    # is exactly what two people reporting one flood should produce. Merging two separate
    # incidents is a human decision behind /merge.
    if candidates:
        incident_id = UUID(candidates[0].existing_id)
        incident = await queries.get_incident(session, incident_id)
        await queries.link_report(
            session,
            raw_report_id=report_id,
            incident_id=incident_id,
            similarity=0.0,
            linked_by=dedup.METHOD,
        )
        public_ref = incident["public_ref"] if incident else None
    else:
        incident = await queries.insert_incident(
            session,
            public_ref=_public_ref(),
            gn_division_id=division.gn_division_id,
            gn_division_code=division.gn_division_code,
            type=incident_type,
            subtype=None,
            summary=None,
            lon=point.lon if point else None,
            lat=point.lat if point else None,
            location_confidence=None,
            people_at_risk=intake.people_at_risk or 0,
            severity=3,
            status="REPORTED",
            first_reported_at=intake.received_at,
            correlation_id=intake.correlation_id,
        )
        incident_id = UUID(incident["id"])
        public_ref = incident["public_ref"]
        await queries.link_report(
            session,
            raw_report_id=report_id,
            incident_id=incident_id,
            similarity=1.0,
            linked_by="intake",
        )

    await queries.set_report_status(session, report_id, "LINKED")

    # 5. Score it.
    result = triage.score(
        triage.TriageInput(
            incident_type=incident_type,
            people_at_risk=intake.people_at_risk or 0,
            minutes_since_reported=0.0,
        )
    )
    await queries.insert_triage(
        session,
        incident_id=incident_id,
        score=result.score,
        model_version=result.model_version,
        factors=json.dumps(result.factors),
        correlation_id=intake.correlation_id,
    )

    # 6. One transaction, one commit, by the caller.
    await _enqueue_received(
        session, intake, report_id, placed=True, has_location=True, incident_id=incident_id
    )

    return IntakeResult(
        report_id=report["id"],
        incident_id=str(incident_id),
        public_ref=public_ref,
        duplicate_candidates=[
            {
                "incident_id": candidate.existing_id,
                "distance_m": candidate.distance_m,
                "minutes_apart": round(candidate.minutes_apart, 1),
                "reason": candidate.reason,
            }
            for candidate in candidates
        ],
        assisted=assisted,
        placed=True,
    )


async def _enqueue_received(
    session: AsyncSession,
    intake: ReportIntake,
    report_id: UUID,
    *,
    placed: bool,
    has_location: bool,
    incident_id: UUID | None = None,
) -> None:
    """Enqueue the intake event inside the caller's transaction.

    The payload carries identifiers and the channel, never the report text. An event log
    is read by more people and kept longer than the record it describes, and the text is
    what a frightened person typed.
    """
    envelope = EventEnvelope(
        event_type=catalogue.INCIDENT_REPORT_RECEIVED,
        producer=SERVICE,
        correlation_id=UUID(intake.correlation_id) if _is_uuid(intake.correlation_id) else uuid7(),
        subject=str(report_id),
        payload={
            "report_id": str(report_id),
            "incident_id": str(incident_id) if incident_id else None,
            "channel": intake.channel,
            "placed": placed,
            "has_location": has_location,
        },
    )
    enqueue(session, OutboxEvent, envelope)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True
