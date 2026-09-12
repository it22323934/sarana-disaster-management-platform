"""Reads and writes over the incident schema.

Plain SQL returning dictionaries, for the same reason as core-api's hierarchy queries: a
detached ORM object that lazy-loads on attribute access is a latent database call in a
place that cannot afford one.

Every parameter compared against NULL is cast explicitly. asyncpg prepares statements and
cannot infer the type of a bare parameter in `:x IS NULL`, which fails at runtime rather
than at import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.domain.ids import uuid7

_INSERT_REPORT = """
INSERT INTO incident.raw_report (
    id, correlation_id, channel, received_at, sender_msisdn_hash, sender_household_id,
    raw_text, reported_language, reported_location, location_accuracy_m, location_source,
    processing_status
) VALUES (
    :id, :correlation_id, :channel, CAST(:received_at AS timestamptz),
    :sender_msisdn_hash, CAST(:sender_household_id AS uuid),
    :raw_text, :reported_language,
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                      CAST(:lat AS double precision)), 4326)::geography
    END,
    CAST(:location_accuracy_m AS integer), :location_source, :processing_status
)
RETURNING id::text, correlation_id, channel, received_at, processing_status
"""

_GET_REPORT = """
SELECT r.id::text, r.correlation_id, r.channel, r.received_at, r.raw_text,
       r.reported_language, r.location_accuracy_m, r.location_source,
       r.processing_status, r.sender_household_id::text,
       ST_X(r.reported_location::geometry) AS lon,
       ST_Y(r.reported_location::geometry) AS lat
FROM incident.raw_report r
WHERE r.id = :report_id
"""

_UPDATE_REPORT_STATUS = """
UPDATE incident.raw_report
SET processing_status = :status
WHERE id = :report_id
RETURNING id::text, processing_status
"""

_INSERT_INCIDENT = """
INSERT INTO incident.incident (
    id, public_ref, gn_division_id, gn_division_code, type, subtype, summary,
    location, location_confidence, people_at_risk, severity, status,
    first_reported_at, correlation_id
) VALUES (
    :id, :public_ref, CAST(:gn_division_id AS uuid), :gn_division_code, :type,
    CAST(:subtype AS text), CAST(:summary AS jsonb),
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                      CAST(:lat AS double precision)), 4326)::geography
    END,
    CAST(:location_confidence AS numeric), :people_at_risk, :severity, :status,
    CAST(:first_reported_at AS timestamptz), :correlation_id
)
RETURNING id::text, public_ref, status, gn_division_code, type
"""

_LINK_REPORT = """
INSERT INTO incident.report_incident_link (id, raw_report_id, incident_id, similarity, linked_by)
VALUES (:id, :raw_report_id, :incident_id, :similarity, :linked_by)
ON CONFLICT (raw_report_id, incident_id) DO NOTHING
RETURNING id::text
"""

_GET_INCIDENT = """
SELECT i.id::text, i.public_ref, i.gn_division_id::text, i.gn_division_code, i.type,
       i.subtype, i.summary, i.people_at_risk, i.severity, i.status,
       i.first_reported_at, i.verified_at, i.resolved_at, i.correlation_id,
       i.cluster_id::text, i.is_cluster_primary,
       ST_X(i.location::geometry) AS lon,
       ST_Y(i.location::geometry) AS lat
FROM incident.incident i
WHERE i.id = :incident_id
"""

# The reports behind one incident, with the transcription that decided each one's fate.
#
# **No column here identifies a person.** `sender_msisdn_hash` and `sender_household_id`
# are deliberately not selected: the console renders this pane to a dispatcher who needs
# the words and the confidence, not the caller. A query that never selects a name cannot
# leak one, which is a stronger guarantee than redacting it downstream.
#
# The LATERAL picks the most recent transcription per report rather than joining all of
# them, because a report re-transcribed after a human correction has two rows and the
# older one is the machine's rejected guess. Showing both would put a superseded
# transcript beside the corrected one with nothing to say which is which.
_INCIDENT_REPORTS = """
SELECT r.id::text AS report_id,
       l.similarity,
       l.linked_by,
       r.channel,
       r.received_at,
       r.raw_text,
       r.reported_language,
       r.raw_audio_uri,
       r.location_source,
       r.location_accuracy_m,
       r.processing_status,
       t.detected_language,
       t.text_original,
       t.text_en,
       t.confidence,
       t.needs_human_review,
       t.reviewed_at
FROM incident.report_incident_link l
JOIN incident.raw_report r ON r.id = l.raw_report_id
LEFT JOIN LATERAL (
    SELECT tr.detected_language, tr.text_original, tr.text_en, tr.confidence,
           tr.needs_human_review, tr.reviewed_at,
           COALESCE(tr.reviewed_text, tr.text_original) AS best_text
    FROM incident.report_transcription tr
    WHERE tr.raw_report_id = r.id
    ORDER BY tr.created_at DESC
    LIMIT 1
) t ON true
WHERE l.incident_id = :incident_id
ORDER BY r.received_at
LIMIT :limit
"""

# The other incidents dedup folded into this one's cluster, with when each arrived.
#
# `similarity` lives on the report link rather than here, so the sibling row carries the
# cluster relationship and not a number: an incident is merged into a cluster by a human
# or by the dedup rule, and quoting a similarity for the pair would imply a comparison
# that was never made between these two rows.
_CLUSTER_SIBLINGS = """
SELECT i.id::text, i.public_ref, i.status, i.type, i.severity,
       i.gn_division_code, i.is_cluster_primary, i.first_reported_at
FROM incident.incident i
WHERE i.cluster_id = CAST(:cluster_id AS uuid)
  AND i.id <> :incident_id
ORDER BY i.first_reported_at
LIMIT 50
"""

_LIST_INCIDENTS = """
SELECT i.id::text, i.public_ref, i.gn_division_id::text, i.gn_division_code, i.type,
       i.status, i.people_at_risk, i.severity, i.first_reported_at,
       ST_X(i.location::geometry) AS lon,
       ST_Y(i.location::geometry) AS lat
FROM incident.incident i
WHERE (CAST(:status AS text) IS NULL OR i.status = CAST(:status AS text))
  AND (CAST(:gn AS text) IS NULL OR i.gn_division_code = CAST(:gn AS text))
  AND (CAST(:since AS timestamptz) IS NULL
       OR i.first_reported_at >= CAST(:since AS timestamptz))
  AND (CAST(:min_lon AS double precision) IS NULL
       OR i.location::geometry && ST_MakeEnvelope(
              CAST(:min_lon AS double precision), CAST(:min_lat AS double precision),
              CAST(:max_lon AS double precision), CAST(:max_lat AS double precision), 4326))
ORDER BY i.first_reported_at DESC
LIMIT :limit OFFSET :offset
"""

# Open incidents in one division within the dedup window. Deliberately narrow: the whole
# point of the window is to avoid scanning every open incident on a bad day.
_DEDUP_CANDIDATES = """
SELECT i.id::text, i.gn_division_code, i.type, i.first_reported_at,
       ST_X(i.location::geometry) AS lon,
       ST_Y(i.location::geometry) AS lat
FROM incident.incident i
WHERE i.gn_division_code = :gn_division_code
  AND i.type = :type
  AND i.first_reported_at >= CAST(:since AS timestamptz)
  AND i.status NOT IN ('RESOLVED', 'REJECTED', 'DUPLICATE')
ORDER BY i.first_reported_at DESC
LIMIT 50
"""

_UPDATE_INCIDENT_STATUS = """
UPDATE incident.incident
SET status = :status,
    verified_at = CASE WHEN :status = 'VERIFIED' THEN now() ELSE verified_at END,
    resolved_at = CASE WHEN :status = 'RESOLVED' THEN now() ELSE resolved_at END
WHERE id = :incident_id
RETURNING id::text, status
"""

_SET_CLUSTER = """
UPDATE incident.incident
SET cluster_id = CAST(:cluster_id AS uuid), is_cluster_primary = :primary
WHERE id = :incident_id
RETURNING id::text, cluster_id::text, is_cluster_primary
"""

_INSERT_TRIAGE = """
INSERT INTO incident.triage_score (
    id, incident_id, scored_at, score, model_version, factors, rank_in_queue, correlation_id
) VALUES (
    :id, :incident_id, now(), :score, :model_version, CAST(:factors AS jsonb),
    CAST(:rank_in_queue AS integer), :correlation_id
)
RETURNING id::text, incident_id::text, score, model_version
"""

# The dispatcher's queue: every open incident with its most recent score. A LEFT JOIN so
# an incident nobody has scored still appears - an unranked incident must never be
# invisible, which is the failure mode that leaves someone waiting.
_QUEUE = """
SELECT DISTINCT ON (i.id)
       i.id::text, i.public_ref, i.gn_division_code, i.type, i.status,
       i.people_at_risk, i.severity, i.first_reported_at,
       t.score, t.model_version, t.factors,
       ST_X(i.location::geometry) AS lon,
       ST_Y(i.location::geometry) AS lat
FROM incident.incident i
LEFT JOIN incident.triage_score t ON t.incident_id = i.id
WHERE i.status IN ('REPORTED', 'VERIFIED', 'TRIAGED')
ORDER BY i.id, t.scored_at DESC NULLS LAST
"""

_GET_PLAN = """
SELECT p.id, p.incident_ids, p.responder_ids, p.route, p.estimated_duration_min,
       p.proposed_at, p.proposed_by_agent, p.status, p.signed_off_by, p.signed_off_at,
       p.rejection_reason, p.langgraph_thread_id, p.correlation_id
FROM incident.dispatch_plan p
WHERE p.id = :plan_id
"""

_LIST_PLANS = """
SELECT p.id::text, p.incident_ids, p.responder_ids, p.estimated_duration_min,
       p.proposed_at, p.proposed_by_agent, p.status, p.signed_off_by::text,
       p.signed_off_at, p.rejection_reason, p.correlation_id
FROM incident.dispatch_plan p
WHERE (CAST(:status AS text) IS NULL OR p.status = CAST(:status AS text))
ORDER BY p.proposed_at DESC
LIMIT :limit OFFSET :offset
"""

_INSERT_PLAN = """
INSERT INTO incident.dispatch_plan (
    id, incident_ids, responder_ids, route, estimated_duration_min,
    proposed_by_agent, status, langgraph_thread_id, correlation_id
) VALUES (
    :id, CAST(:incident_ids AS uuid[]), CAST(:responder_ids AS uuid[]),
    CAST(:route AS jsonb), CAST(:estimated_duration_min AS integer),
    :proposed_by_agent, :status, CAST(:langgraph_thread_id AS text), :correlation_id
)
RETURNING id::text, status, proposed_at
"""

# The only writer of signed_off_by. The database trigger refuses RELEASED without one, so
# this statement and that trigger are the two halves of the same guarantee.
_RELEASE_PLAN = """
UPDATE incident.dispatch_plan
SET status = 'RELEASED', signed_off_by = :approver_id, signed_off_at = now()
WHERE id = :plan_id AND signed_off_by IS NULL
RETURNING id::text, status, signed_off_by::text, signed_off_at
"""

_REJECT_PLAN = """
UPDATE incident.dispatch_plan
SET status = 'REJECTED', rejection_reason = :reason
WHERE id = :plan_id AND status NOT IN ('RELEASED', 'COMPLETED', 'REJECTED')
RETURNING id::text, status, rejection_reason
"""

_LIST_RESPONDERS = """
SELECT r.id::text, r.org, r.type, r.capacity, r.status,
       r.home_gn_division_id::text,
       ST_X(r.current_location::geometry) AS lon,
       ST_Y(r.current_location::geometry) AS lat
FROM incident.responder r
WHERE (CAST(:available AS boolean) IS NULL
       OR (CAST(:available AS boolean) = true AND r.status = 'AVAILABLE')
       OR (CAST(:available AS boolean) = false AND r.status <> 'AVAILABLE'))
ORDER BY r.org, r.type
LIMIT :limit
"""

_REVIEW_QUEUE = """
SELECT t.id::text, t.raw_report_id::text, t.provider, t.model, t.detected_language,
       t.text_original, t.text_en, t.confidence, t.needs_human_review,
       t.reviewed_by::text, t.reviewed_at, r.channel, r.received_at
FROM incident.report_transcription t
JOIN incident.raw_report r ON r.id = t.raw_report_id
WHERE t.needs_human_review = true AND t.reviewed_at IS NULL
ORDER BY r.received_at
LIMIT :limit OFFSET :offset
"""

_RESOLVE_REVIEW = """
UPDATE incident.report_transcription
SET reviewed_by = :reviewer_id, reviewed_text = :text, reviewed_at = now(),
    needs_human_review = false
WHERE id = :transcription_id AND reviewed_at IS NULL
RETURNING id::text, raw_report_id::text, reviewed_at
"""


async def insert_report(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_REPORT), {"id": uuid7(), **values})
    return dict(result.mappings().one())


async def get_report(session: AsyncSession, report_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_REPORT), {"report_id": report_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def set_report_status(
    session: AsyncSession, report_id: UUID, status: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_UPDATE_REPORT_STATUS), {"report_id": report_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_incident(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_INCIDENT), {"id": uuid7(), **values})
    return dict(result.mappings().one())


async def link_report(
    session: AsyncSession,
    *,
    raw_report_id: UUID,
    incident_id: UUID,
    similarity: float,
    linked_by: str,
) -> None:
    await session.execute(
        text(_LINK_REPORT),
        {
            "id": uuid7(),
            "raw_report_id": raw_report_id,
            "incident_id": incident_id,
            "similarity": similarity,
            "linked_by": linked_by,
        },
    )


async def get_incident(session: AsyncSession, incident_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_INCIDENT), {"incident_id": incident_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def incident_reports(
    session: AsyncSession, incident_id: UUID, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Every report linked to this incident, oldest first.

    Oldest first because the first report is the one that opened the incident and the ones
    after it are corroboration. Reversing that would put the newest fragment at the top of
    a pane whose whole job is to say what was originally reported.
    """
    result = await session.execute(
        text(_INCIDENT_REPORTS), {"incident_id": incident_id, "limit": limit}
    )
    return [dict(row) for row in result.mappings()]


async def cluster_siblings(
    session: AsyncSession, cluster_id: UUID, incident_id: UUID
) -> list[dict[str, Any]]:
    """The other incidents in this one's dedup cluster."""
    result = await session.execute(
        text(_CLUSTER_SIBLINGS), {"cluster_id": cluster_id, "incident_id": incident_id}
    )
    return [dict(row) for row in result.mappings()]


async def list_incidents(
    session: AsyncSession,
    *,
    status: str | None = None,
    gn: str | None = None,
    since: datetime | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    min_lon, min_lat, max_lon, max_lat = bbox if bbox else (None, None, None, None)
    result = await session.execute(
        text(_LIST_INCIDENTS),
        {
            "status": status,
            "gn": gn,
            "since": since,
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]


async def dedup_candidates(
    session: AsyncSession, *, gn_division_code: str, incident_type: str, since: datetime
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_DEDUP_CANDIDATES),
        {"gn_division_code": gn_division_code, "type": incident_type, "since": since},
    )
    return [dict(row) for row in result.mappings()]


async def set_incident_status(
    session: AsyncSession, incident_id: UUID, status: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_UPDATE_INCIDENT_STATUS), {"incident_id": incident_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def set_cluster(
    session: AsyncSession, incident_id: UUID, *, cluster_id: UUID | None, primary: bool
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_SET_CLUSTER),
        {"incident_id": incident_id, "cluster_id": cluster_id, "primary": primary},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_triage(
    session: AsyncSession,
    *,
    incident_id: UUID,
    score: float,
    model_version: str,
    factors: str,
    correlation_id: str,
    rank_in_queue: int | None = None,
) -> dict[str, Any]:
    result = await session.execute(
        text(_INSERT_TRIAGE),
        {
            "id": uuid7(),
            "incident_id": incident_id,
            "score": score,
            "model_version": model_version,
            "factors": factors,
            "rank_in_queue": rank_in_queue,
            "correlation_id": correlation_id,
        },
    )
    return dict(result.mappings().one())


async def queue_rows(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(text(_QUEUE))
    return [dict(row) for row in result.mappings()]


async def get_plan(session: AsyncSession, plan_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_PLAN), {"plan_id": plan_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_plans(
    session: AsyncSession, *, status: str | None = None, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_PLANS), {"status": status, "limit": limit, "offset": offset}
    )
    return [dict(row) for row in result.mappings()]


async def insert_plan(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_PLAN), {"id": uuid7(), **values})
    return dict(result.mappings().one())


async def release_plan(
    session: AsyncSession, plan_id: UUID, approver_id: UUID
) -> dict[str, Any] | None:
    """Release a plan. Returns None if it already carried a sign-off.

    The `signed_off_by IS NULL` predicate makes a concurrent double-approve resolve to one
    winner in the database rather than in the application, so two dispatchers pressing the
    button at the same instant cannot both succeed.
    """
    result = await session.execute(
        text(_RELEASE_PLAN), {"plan_id": plan_id, "approver_id": approver_id}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def reject_plan(session: AsyncSession, plan_id: UUID, reason: str) -> dict[str, Any] | None:
    result = await session.execute(text(_REJECT_PLAN), {"plan_id": plan_id, "reason": reason})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_responders(
    session: AsyncSession, *, available: bool | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    result = await session.execute(text(_LIST_RESPONDERS), {"available": available, "limit": limit})
    return [dict(row) for row in result.mappings()]


async def review_queue(
    session: AsyncSession, *, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    result = await session.execute(text(_REVIEW_QUEUE), {"limit": limit, "offset": offset})
    return [dict(row) for row in result.mappings()]


async def resolve_review(
    session: AsyncSession, transcription_id: UUID, *, reviewer_id: UUID, corrected: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_RESOLVE_REVIEW),
        {"transcription_id": transcription_id, "reviewer_id": reviewer_id, "text": corrected},
    )
    row = result.mappings().first()
    return dict(row) if row else None
