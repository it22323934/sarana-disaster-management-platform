"""Reads and writes over the `aid` schema.

Plain SQL returning dictionaries. Every parameter compared against NULL is cast
explicitly: asyncpg prepares statements and cannot infer the type of a bare parameter in
`:x IS NULL`, which fails at runtime rather than at import.

Two things here are unusual and deliberate.

`approval` and `disbursement` are never inserted from this module. They go through
`repo.chain_writer`, which reads the chain tail and supplies `prev_hash` and `entry_hash`
computed with the published RFC 8785 scheme. An INSERT that skipped it would be refused by
the trigger, which is the point.

The public queries select from aggregates only. `_PUBLIC_LEDGER` names no household, no
assessment and no division below district, because the anonymisation has to be a property
of the query rather than of a serialiser somebody may later change.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------------------
# Cost schedules
# --------------------------------------------------------------------------------------

_LIST_SCHEDULES = """
SELECT s.id::text, s.version, s.published_at, s.source_ref,
       s.effective_from, s.effective_to
FROM aid.cost_schedule s
ORDER BY s.effective_from DESC, s.version DESC
"""

_SCHEDULE_LINES = """
SELECT l.id::text, l.cost_schedule_id::text, l.category, l.subcategory,
       l.description, l.unit, l.rate_lkr_cents, l.cap_lkr_cents, l.formula
FROM aid.cost_schedule_line l
ORDER BY l.category, l.subcategory
"""

_SCHEDULE_IN_FORCE = """
SELECT id::text, version
FROM aid.cost_schedule
WHERE effective_from <= :on_date
  AND (effective_to IS NULL OR effective_to > :on_date)
ORDER BY effective_from DESC
LIMIT 1
"""


async def list_cost_schedules(session: AsyncSession) -> list[dict[str, Any]]:
    """Every published schedule, newest first. Public - no auth, no scope."""
    result = await session.execute(text(_LIST_SCHEDULES))
    return [dict(row) for row in result.mappings()]


async def cost_schedule_lines(session: AsyncSession) -> list[dict[str, Any]]:
    """Every line of every schedule, with the formula as published."""
    result = await session.execute(text(_SCHEDULE_LINES))
    return [dict(row) for row in result.mappings()]


async def schedule_in_force(session: AsyncSession, on_date: date) -> dict[str, Any] | None:
    """The schedule that was in force on a given day.

    Assessment date, not today. A schedule published after the cyclone does not move an
    entitlement that was already calculated.
    """
    result = await session.execute(text(_SCHEDULE_IN_FORCE), {"on_date": on_date})
    row = result.mappings().first()
    return dict(row) if row else None


# --------------------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------------------

_INSERT_ASSESSMENT = """
INSERT INTO aid.damage_assessment
    (id, public_ref, household_id, gn_division_id, gn_division_code, hazard_event_id,
     assessed_by, assessed_at, category, subcategory, cost_estimate_lkr_cents,
     evidence_photo_uris, evidence_hash, gps_at_assessment, gps_accuracy_m,
     client_operation_id, status, correlation_id)
VALUES (:id, :public_ref, :household_id, :gn_division_id, :gn_division_code,
        :hazard_event_id, :assessed_by, COALESCE(:assessed_at, now()), :category,
        :subcategory, :cost_estimate_lkr_cents,
        CAST(:evidence_photo_uris AS text[]), :evidence_hash,
        CASE WHEN CAST(:longitude AS double precision) IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(CAST(:longitude AS double precision),
                                          CAST(:latitude AS double precision)), 4326)::geography
        END,
        :gps_accuracy_m, :client_operation_id, :status, :correlation_id)
ON CONFLICT (client_operation_id) DO NOTHING
RETURNING id::text, public_ref, status
"""

_GET_ASSESSMENT = """
SELECT a.id::text, a.public_ref, a.household_id::text, a.gn_division_code,
       a.hazard_event_id::text, a.assessed_by::text, a.assessed_at, a.category,
       a.subcategory, a.cost_estimate_lkr_cents, a.evidence_hash, a.gps_accuracy_m,
       a.client_operation_id, a.status, a.correlation_id, a.created_at
FROM aid.damage_assessment a
WHERE a.id = :assessment_id
"""

_LIST_ASSESSMENTS = """
SELECT a.id::text, a.public_ref, a.household_id::text, a.gn_division_code,
       a.hazard_event_id::text, a.assessed_by::text, a.assessed_at, a.category,
       a.cost_estimate_lkr_cents, a.status
FROM aid.damage_assessment a
WHERE (CAST(:status AS text) IS NULL OR a.status = CAST(:status AS text))
  AND (CAST(:division AS text) IS NULL OR a.gn_division_code LIKE CAST(:division AS text) || '%')
  AND (CAST(:hazard_event_id AS uuid) IS NULL
       OR a.hazard_event_id = CAST(:hazard_event_id AS uuid))
ORDER BY a.assessed_at DESC
LIMIT :limit OFFSET :offset
"""

_SET_ASSESSMENT_STATUS = """
UPDATE aid.damage_assessment
SET status = :status
WHERE id = :assessment_id
  AND status IN ('SUBMITTED', 'UNDER_REVIEW')
RETURNING id::text, public_ref, status, household_id::text, gn_division_code,
          category, cost_estimate_lkr_cents, assessed_by::text, assessed_at
"""

_ASSESSMENT_BY_OPERATION = """
SELECT id::text, public_ref, status
FROM aid.damage_assessment
WHERE client_operation_id = :client_operation_id
"""

_APPLIED_OPERATION_IDS = """
SELECT client_operation_id
FROM aid.damage_assessment
WHERE client_operation_id = ANY(CAST(:operation_ids AS text[]))
"""


async def insert_assessment(session: AsyncSession, **values: Any) -> dict[str, Any] | None:
    """Store one assessment, or return None if its operation id is already on record.

    `ON CONFLICT DO NOTHING` rather than an upsert: a replayed operation must not rewrite
    an assessment an officer may already have reviewed.
    """
    result = await session.execute(text(_INSERT_ASSESSMENT), values)
    row = result.mappings().first()
    return dict(row) if row else None


async def get_assessment(session: AsyncSession, assessment_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_ASSESSMENT), {"assessment_id": assessment_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_assessments(
    session: AsyncSession,
    *,
    status: str | None = None,
    division: str | None = None,
    hazard_event_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_ASSESSMENTS),
        {
            "status": status,
            "division": division,
            "hazard_event_id": hazard_event_id,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]


async def set_assessment_status(
    session: AsyncSession, assessment_id: UUID, status: str
) -> dict[str, Any] | None:
    """Accept or reject. Returns None if the assessment is not in a reviewable state."""
    result = await session.execute(
        text(_SET_ASSESSMENT_STATUS), {"assessment_id": assessment_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def assessment_by_operation_id(
    session: AsyncSession, client_operation_id: str
) -> dict[str, Any] | None:
    """The assessment a replayed operation id already produced.

    Lets a retrying device be told what its earlier attempt created rather than merely
    that it was a duplicate, which is the difference between a device that can move on
    and one that keeps asking.
    """
    result = await session.execute(
        text(_ASSESSMENT_BY_OPERATION), {"client_operation_id": client_operation_id}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def applied_operation_ids(session: AsyncSession, operation_ids: list[str]) -> set[str]:
    """Which of these client operation ids are already stored."""
    if not operation_ids:
        return set()
    result = await session.execute(text(_APPLIED_OPERATION_IDS), {"operation_ids": operation_ids})
    return {row[0] for row in result}


# --------------------------------------------------------------------------------------
# Device sync cursors
# --------------------------------------------------------------------------------------

# FOR UPDATE, so two concurrent pushes from the same device serialise. Without it both
# read the same cursor, both believe they are next in sequence, and the ordering rule the
# whole sync contract rests on quietly stops holding.
_LOCK_CURSOR = """
SELECT device_id, last_applied_seq, blocked_on_seq
FROM aid.device_sync_cursor
WHERE device_id = :device_id
FOR UPDATE
"""

_UPSERT_CURSOR = """
INSERT INTO aid.device_sync_cursor (device_id, last_applied_seq, blocked_on_seq, last_synced_at)
VALUES (:device_id, :last_applied_seq, CAST(:blocked_on_seq AS bigint), now())
ON CONFLICT (device_id) DO UPDATE
SET last_applied_seq = GREATEST(
        aid.device_sync_cursor.last_applied_seq, EXCLUDED.last_applied_seq),
    blocked_on_seq = EXCLUDED.blocked_on_seq,
    last_synced_at = now()
RETURNING device_id, last_applied_seq, blocked_on_seq
"""


async def lock_device_cursor(session: AsyncSession, device_id: str) -> dict[str, Any]:
    """This device's cursor, locked for the rest of the transaction.

    A device with no cursor has applied nothing, which is seq 0.
    """
    result = await session.execute(text(_LOCK_CURSOR), {"device_id": device_id})
    row = result.mappings().first()
    if row:
        return dict(row)
    return {"device_id": device_id, "last_applied_seq": 0, "blocked_on_seq": None}


async def save_device_cursor(
    session: AsyncSession, *, device_id: str, last_applied_seq: int, blocked_on_seq: int | None
) -> dict[str, Any]:
    """Move the cursor forward. GREATEST, so a late batch can never rewind it."""
    result = await session.execute(
        text(_UPSERT_CURSOR),
        {
            "device_id": device_id,
            "last_applied_seq": last_applied_seq,
            "blocked_on_seq": blocked_on_seq,
        },
    )
    return dict(result.mappings().one())


# --------------------------------------------------------------------------------------
# Entitlements
# --------------------------------------------------------------------------------------

_INSERT_ENTITLEMENT = """
INSERT INTO aid.entitlement
    (id, assessment_id, cost_schedule_id, cost_schedule_version, calculated_lkr_cents,
     calculation_trace, status, correlation_id)
VALUES (:id, :assessment_id, :cost_schedule_id, :cost_schedule_version,
        :calculated_lkr_cents, CAST(:calculation_trace AS jsonb), :status, :correlation_id)
RETURNING id::text, assessment_id::text, calculated_lkr_cents, cost_schedule_version, status
"""

_GET_ENTITLEMENT = """
SELECT e.id::text, e.assessment_id::text, e.cost_schedule_id::text,
       e.cost_schedule_version, e.calculated_lkr_cents, e.calculation_trace,
       e.calculated_at, e.status, e.correlation_id,
       a.public_ref AS assessment_ref, a.household_id::text, a.gn_division_code,
       a.assessed_by::text
FROM aid.entitlement e
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE e.id = :entitlement_id
"""

_SET_ENTITLEMENT_STATUS = """
UPDATE aid.entitlement
SET status = :status
WHERE id = :entitlement_id
RETURNING id::text, status
"""

# Everything the disbursement gate needs, read once. The gate is pure and never reaches
# back into the database mid-decision, which is what makes the order of its checks
# testable rather than merely documented.
_RELEASE_CONTEXT = """
SELECT e.id::text AS entitlement_id,
       e.calculated_lkr_cents,
       e.status AS entitlement_status,
       a.gn_division_code,
       a.assessed_by::text AS assessor_id,
       a.household_id::text,
       -- Live payments only. A reversed disbursement is money that came back, so the
       -- entitlement is unpaid again and must be releasable; the row stays visible to an
       -- auditor either way.
       EXISTS (SELECT 1 FROM aid.disbursement d
                WHERE d.entitlement_id = e.id AND d.reversed_at IS NULL)
           AS already_released
FROM aid.entitlement e
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE e.id = :entitlement_id
"""

_APPROVALS_FOR = """
SELECT id::text, level, approver_id::text, decision, decided_at, reason
FROM aid.approval
WHERE entitlement_id = :entitlement_id
ORDER BY seq
"""

# Open grievances against *this* entitlement, its assessment, or a disbursement already
# made on it. A grievance elsewhere in the district stops nothing: a complaints process
# that halts unrelated aid teaches everyone not to complain.
_OPEN_GRIEVANCES_FOR = """
SELECT g.id::text, g.public_ref, g.status, g.subject_type
FROM aid.grievance g
WHERE g.status IN ('RECEIVED', 'ACKNOWLEDGED', 'UNDER_REVIEW', 'ESCALATED')
  AND (
        (g.subject_type = 'ENTITLEMENT' AND g.subject_id = :entitlement_id)
     OR (g.subject_type = 'ASSESSMENT'
         AND g.subject_id = (SELECT assessment_id FROM aid.entitlement
                             WHERE id = :entitlement_id))
     OR (g.subject_type = 'DISBURSEMENT'
         AND g.subject_id IN (SELECT id FROM aid.disbursement
                              WHERE entitlement_id = :entitlement_id))
  )
"""


async def insert_entitlement(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_ENTITLEMENT), values)
    return dict(result.mappings().one())


async def get_entitlement(session: AsyncSession, entitlement_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_ENTITLEMENT), {"entitlement_id": entitlement_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def set_entitlement_status(
    session: AsyncSession, entitlement_id: UUID, status: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_SET_ENTITLEMENT_STATUS), {"entitlement_id": entitlement_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def release_context_row(session: AsyncSession, entitlement_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_RELEASE_CONTEXT), {"entitlement_id": entitlement_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def approvals_for(session: AsyncSession, entitlement_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(text(_APPROVALS_FOR), {"entitlement_id": entitlement_id})
    return [dict(row) for row in result.mappings()]


async def open_grievances_for(session: AsyncSession, entitlement_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(text(_OPEN_GRIEVANCES_FOR), {"entitlement_id": entitlement_id})
    return [dict(row) for row in result.mappings()]


# --------------------------------------------------------------------------------------
# The ledger, authenticated
# --------------------------------------------------------------------------------------

_LEDGER_PAGE = """
SELECT d.seq, d.id::text, d.entitlement_id::text, d.amount_lkr_cents,
       d.released_by::text, d.released_at, d.payment_rail, d.payment_ref,
       d.prev_hash, d.entry_hash, d.citizen_confirmed, d.citizen_confirmed_at,
       a.gn_division_code, a.household_id::text, a.public_ref AS assessment_ref
FROM aid.disbursement d
JOIN aid.entitlement e ON e.id = d.entitlement_id
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE d.seq >= :from_seq
  AND (CAST(:to_seq AS bigint) IS NULL OR d.seq <= CAST(:to_seq AS bigint))
ORDER BY d.seq
LIMIT :limit
"""

_GET_DISBURSEMENT = """
SELECT d.seq, d.id::text, d.entitlement_id::text, d.amount_lkr_cents,
       d.released_by::text, d.released_at, d.payment_rail, d.payment_ref,
       d.prev_hash, d.entry_hash, d.citizen_confirmed, d.citizen_confirmed_at,
       a.household_id::text, a.gn_division_code
FROM aid.disbursement d
JOIN aid.entitlement e ON e.id = d.entitlement_id
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE d.id = :disbursement_id
"""

# The one permitted UPDATE on `disbursement`, opened by migration 0008. Everything else
# on the table is still append-only: the trigger compares every other column and refuses
# the write if any of them moved, and `sarana_app` holds UPDATE on these three columns
# only. The household answering is evidence about an entry, not a revision of it, which is
# also why the confirmation columns are outside the hashed payload.
_RECORD_CONFIRMATION = """
UPDATE aid.disbursement
SET citizen_confirmed = true,
    citizen_confirmed_at = now(),
    citizen_confirm_channel = :channel
WHERE id = :disbursement_id AND citizen_confirmed = false
RETURNING id::text, entitlement_id::text, citizen_confirmed_at
"""


async def ledger_page(
    session: AsyncSession, *, from_seq: int = 0, to_seq: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LEDGER_PAGE), {"from_seq": from_seq, "to_seq": to_seq, "limit": limit}
    )
    return [dict(row) for row in result.mappings()]


async def get_disbursement(session: AsyncSession, disbursement_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_DISBURSEMENT), {"disbursement_id": disbursement_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def record_citizen_confirmation(
    session: AsyncSession, *, disbursement_id: UUID, channel: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_RECORD_CONFIRMATION), {"disbursement_id": disbursement_id, "channel": channel}
    )
    row = result.mappings().first()
    return dict(row) if row else None


# --------------------------------------------------------------------------------------
# The ledger, public
# --------------------------------------------------------------------------------------

# The per-entry public feed. This is what `tools/sarana-verify` recomputes, so it carries
# each entry's hashes and every field the hash covers - and nothing else.
#
# What is absent is the point: no household id, no GN division, no assessment reference, no
# coordinate, no name, no NIC, no phone. `entitlement_id` and `released_by` are UUIDs with
# no public resolver, and `released_by` stays because a ledger that does not commit to who
# released public money is not an accountability record.
#
# `released_at` is rendered to a string in SQL rather than left as a timestamp, so the
# published bytes and the hashed bytes are identical regardless of which JSON serialiser
# runs. `+00:00` versus `Z` would break every hash in the feed.
_PUBLIC_LEDGER_ENTRIES = """
SELECT d.seq,
       d.entitlement_id::text,
       d.amount_lkr_cents,
       d.released_by::text,
       TO_CHAR(d.released_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00')
           AS released_at,
       d.payment_rail,
       d.payment_ref,
       d.prev_hash,
       d.entry_hash,
       DATE(d.released_at AT TIME ZONE 'Asia/Colombo')::text AS anchor_date,
       -- Outside the hashed payload, and `sarana-verify` strips it before recomputing.
       -- Carried anyway because publishing a released payment with no hint that the money
       -- came back is the kind of true-but-misleading number a transparency feed exists to
       -- prevent. The authoritative record is the entry in /ledger/reversals.
       (d.reversed_at IS NOT NULL) AS reversed
FROM aid.disbursement d
WHERE d.seq >= :from_seq
ORDER BY d.seq
LIMIT :limit
"""

# Aggregated to district and day. Names no household, no assessment, no officer and no
# division below district, and carries no geometry at any zoom.
#
# The anonymisation is a property of this query rather than of a serialiser, because a
# serialiser is one careless field addition away from publishing a household id.
_PUBLIC_LEDGER = """
SELECT SPLIT_PART(a.gn_division_code, '-', 1) || '-' ||
       SPLIT_PART(a.gn_division_code, '-', 2) AS district_code,
       DATE(d.released_at AT TIME ZONE 'Asia/Colombo') AS released_on,
       e.cost_schedule_version,
       COUNT(*) AS disbursement_count,
       SUM(d.amount_lkr_cents) AS total_lkr_cents,
       MIN(d.seq) AS first_seq,
       MAX(d.seq) AS last_seq,
       COUNT(*) FILTER (WHERE d.citizen_confirmed) AS citizen_confirmed_count
FROM aid.disbursement d
JOIN aid.entitlement e ON e.id = d.entitlement_id
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE (CAST(:from_date AS date) IS NULL
       OR DATE(d.released_at AT TIME ZONE 'Asia/Colombo') >= CAST(:from_date AS date))
  AND (CAST(:to_date AS date) IS NULL
       OR DATE(d.released_at AT TIME ZONE 'Asia/Colombo') <= CAST(:to_date AS date))
GROUP BY 1, 2, 3
HAVING COUNT(*) >= :min_group_size
ORDER BY 2 DESC, 1
LIMIT :limit
"""

# Grievance counts by district and status. Published because a transparency system that
# hides its own complaint rate is not one.
_PUBLIC_GRIEVANCE_STATS = """
SELECT COALESCE(SPLIT_PART(g.assigned_ds_division_code, '-', 1) || '-' ||
                SPLIT_PART(g.assigned_ds_division_code, '-', 2), 'UNASSIGNED') AS district_code,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE g.status IN
            ('RECEIVED','ACKNOWLEDGED','UNDER_REVIEW','ESCALATED')) AS open_count,
       COUNT(*) FILTER (WHERE g.status IN ('RESOLVED','REJECTED')) AS closed_count,
       COUNT(*) FILTER (WHERE g.status NOT IN ('RESOLVED','REJECTED')
                          AND g.sla_due_at < now()) AS breached_count,
       EXTRACT(EPOCH FROM PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY (g.resolved_at - g.raised_at))) AS median_resolution_seconds
FROM aid.grievance g
GROUP BY 1
ORDER BY 1
"""

_PUBLIC_CONFIRMATION_RATE = """
SELECT COUNT(*) AS released,
       COUNT(*) FILTER (WHERE citizen_confirmed) AS confirmed,
       COUNT(*) FILTER (WHERE NOT citizen_confirmed
                          AND released_at < now() - make_interval(days => :window_days))
           AS unconfirmed,
       COUNT(*) FILTER (WHERE NOT citizen_confirmed
                          AND released_at >= now() - make_interval(days => :window_days))
           AS awaiting
FROM aid.disbursement
"""


async def public_ledger_entries(
    session: AsyncSession, *, from_seq: int = 0, limit: int = 1000
) -> list[dict[str, Any]]:
    """Every entry, anonymised, in seq order - the feed a verifier recomputes.

    Ordered by seq and never filtered by date, because a verifier walking the chain needs
    it unbroken: a gap it cannot distinguish from a removed entry is exactly the alarm the
    chain exists to raise.
    """
    result = await session.execute(
        text(_PUBLIC_LEDGER_ENTRIES), {"from_seq": from_seq, "limit": limit}
    )
    return [dict(row) for row in result.mappings()]


async def public_ledger(
    session: AsyncSession,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    min_group_size: int = 1,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Aggregated disbursement totals. No auth, and nothing identifying at any zoom."""
    result = await session.execute(
        text(_PUBLIC_LEDGER),
        {
            "from_date": from_date,
            "to_date": to_date,
            "min_group_size": min_group_size,
            "limit": limit,
        },
    )
    return [dict(row) for row in result.mappings()]


async def public_grievance_stats(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(text(_PUBLIC_GRIEVANCE_STATS))
    return [dict(row) for row in result.mappings()]


async def confirmation_rate(session: AsyncSession, *, window_days: int = 7) -> dict[str, Any]:
    result = await session.execute(text(_PUBLIC_CONFIRMATION_RATE), {"window_days": window_days})
    return dict(result.mappings().one())


# --------------------------------------------------------------------------------------
# Anchors
# --------------------------------------------------------------------------------------

# `anchor_date` is aliased to `date`, which is what `sarana_shared.crypto.merkle.Anchor`
# calls it and therefore what is inside the S3 object. The published record and the locked
# object are then directly comparable, which is the whole point of publishing it.
_LIST_ANCHORS = """
SELECT anchor_date::text AS date, merkle_root, entry_count, first_seq, last_seq,
       prev_anchor_hash, s3_object_lock_uri, published_at, created_at
FROM aid.ledger_anchor
ORDER BY anchor_date DESC
LIMIT :limit
"""

_LATEST_ANCHOR = """
SELECT anchor_date::text AS date, merkle_root, entry_count, first_seq, last_seq,
       prev_anchor_hash
FROM aid.ledger_anchor
ORDER BY anchor_date DESC
LIMIT 1
"""

_INSERT_ANCHOR = """
INSERT INTO aid.ledger_anchor
    (id, anchor_date, merkle_root, prev_anchor_hash, entry_count, first_seq, last_seq,
     s3_object_lock_uri, published_at)
VALUES (:id, :anchor_date, :merkle_root, :prev_anchor_hash, :entry_count, :first_seq,
        :last_seq, :s3_object_lock_uri, :published_at)
ON CONFLICT (anchor_date) DO NOTHING
RETURNING anchor_date::text AS date, merkle_root, prev_anchor_hash, entry_count,
          first_seq, last_seq
"""

# One Colombo day's entries, in seq order and in the published shape. The Merkle tree is
# built over exactly these payloads, so this SELECT must stay identical to the public feed
# above - anchoring a shape nobody outside can reproduce is the failure the whole scheme
# exists to prevent. Ordering is the chain's own `seq`, never the insertion timestamp.
_ENTRIES_FOR_DAY = """
SELECT d.seq,
       d.entitlement_id::text,
       d.amount_lkr_cents,
       d.released_by::text,
       TO_CHAR(d.released_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00')
           AS released_at,
       d.payment_rail,
       d.payment_ref,
       d.prev_hash,
       d.entry_hash
FROM aid.disbursement d
WHERE DATE(d.released_at AT TIME ZONE 'Asia/Colombo') = :anchor_date
ORDER BY d.seq
"""

_UNANCHORED_DAYS = """
SELECT DISTINCT DATE(d.released_at AT TIME ZONE 'Asia/Colombo') AS anchor_date
FROM aid.disbursement d
WHERE DATE(d.released_at AT TIME ZONE 'Asia/Colombo') < :today
  AND NOT EXISTS (
        SELECT 1 FROM aid.ledger_anchor la
        WHERE la.anchor_date = DATE(d.released_at AT TIME ZONE 'Asia/Colombo'))
ORDER BY 1
"""


async def list_anchors(session: AsyncSession, *, limit: int = 400) -> list[dict[str, Any]]:
    result = await session.execute(text(_LIST_ANCHORS), {"limit": limit})
    return [dict(row) for row in result.mappings()]


async def latest_anchor(session: AsyncSession) -> dict[str, Any] | None:
    result = await session.execute(text(_LATEST_ANCHOR))
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_anchor(session: AsyncSession, **values: Any) -> dict[str, Any] | None:
    result = await session.execute(text(_INSERT_ANCHOR), values)
    row = result.mappings().first()
    return dict(row) if row else None


async def entries_for_day(session: AsyncSession, anchor_date: date) -> list[dict[str, Any]]:
    result = await session.execute(text(_ENTRIES_FOR_DAY), {"anchor_date": anchor_date})
    return [dict(row) for row in result.mappings()]


async def unanchored_days(session: AsyncSession, today: date) -> list[date]:
    """Days with disbursements and no anchor.

    Plural on purpose. If the job did not run for three days, the next run anchors all
    three rather than only yesterday - a missing anchor is a hole in the public proof that
    never fills itself.
    """
    result = await session.execute(text(_UNANCHORED_DAYS), {"today": today})
    return [row[0] for row in result]


# --------------------------------------------------------------------------------------
# Reversals
# --------------------------------------------------------------------------------------

# Everything a reversal needs about the payment it is correcting, in one read: the amount
# that has to come back, the household to raise the grievance for, and the division to
# assign it to. Read once so the decision cannot change under the write.
_REVERSAL_CONTEXT = """
SELECT d.id::text            AS disbursement_id,
       d.entitlement_id::text,
       d.amount_lkr_cents,
       d.payment_ref,
       d.reversed_at,
       a.household_id::text,
       a.gn_division_code
FROM aid.disbursement d
JOIN aid.entitlement e ON e.id = d.entitlement_id
JOIN aid.damage_assessment a ON a.id = e.assessment_id
WHERE d.id = :disbursement_id
"""

_GET_REVERSAL = """
SELECT r.seq, r.id::text, r.disbursement_id::text, r.entitlement_id::text,
       r.amount_lkr_cents, r.reason, r.rail_reference, r.reversed_at,
       r.grievance_id::text, r.prev_hash, r.entry_hash
FROM aid.disbursement_reversal r
WHERE r.disbursement_id = :disbursement_id
"""

# The public reversal feed. Anonymised on exactly the same terms as `_PUBLIC_LEDGER_ENTRIES`
# - no household, no division, no assessment reference - and rendering `reversed_at` to a
# string in SQL for the same reason: the published bytes and the hashed bytes must be
# identical whichever JSON serialiser runs.
_PUBLIC_REVERSALS = """
SELECT r.seq,
       r.disbursement_id::text,
       r.entitlement_id::text,
       r.amount_lkr_cents,
       r.reason,
       r.rail_reference,
       TO_CHAR(r.reversed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00')
           AS reversed_at,
       r.prev_hash,
       r.entry_hash
FROM aid.disbursement_reversal r
WHERE r.seq >= :from_seq
ORDER BY r.seq
LIMIT :limit
"""


# Payments the rail has accepted but that nothing has confirmed settled or failed. The
# settlement poller's work list.
#
# Ordered oldest first: a transfer that has been in flight longest is the one a household
# has been waiting on, and it is the one most likely to have quietly failed.
_PENDING_SETTLEMENT = """
SELECT d.id::text AS disbursement_id,
       d.payment_ref,
       d.payment_rail,
       d.released_at
FROM aid.disbursement d
WHERE d.reversed_at IS NULL
  AND d.payment_ref IS NOT NULL
  AND NOT d.citizen_confirmed
  -- Built from an integer rather than bound as an interval string: asyncpg prepares
  -- statements and refuses to adapt a Python str to interval, which fails at runtime
  -- rather than at import.
  AND d.released_at >= now() - (CAST(:window_days AS integer) * INTERVAL '1 day')
ORDER BY d.released_at
LIMIT :limit
"""


async def pending_settlement(
    session: AsyncSession, *, window_days: int = 30, limit: int = 200
) -> list[dict[str, Any]]:
    """Disbursements whose rail outcome is still unknown.

    Bounded by a window because a payment nobody has resolved in a month is not going to be
    resolved by polling; it is a case for a person. Without the bound the work list grows
    forever and the poller spends its time on the oldest failures rather than the newest.
    """
    result = await session.execute(
        text(_PENDING_SETTLEMENT), {"window_days": window_days, "limit": limit}
    )
    return [dict(row) for row in result.mappings()]


async def reversal_context_row(
    session: AsyncSession, disbursement_id: UUID
) -> dict[str, Any] | None:
    result = await session.execute(text(_REVERSAL_CONTEXT), {"disbursement_id": disbursement_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def get_reversal_for(session: AsyncSession, disbursement_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_REVERSAL), {"disbursement_id": disbursement_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def public_reversals(
    session: AsyncSession, *, from_seq: int = 0, limit: int = 500
) -> list[dict[str, Any]]:
    result = await session.execute(text(_PUBLIC_REVERSALS), {"from_seq": from_seq, "limit": limit})
    return [dict(row) for row in result.mappings()]


# --------------------------------------------------------------------------------------
# Grievances
# --------------------------------------------------------------------------------------

_INSERT_GRIEVANCE = """
INSERT INTO aid.grievance
    (id, public_ref, household_id, subject_type, subject_id, channel, raised_at,
     description, status, assigned_ds_division_id, assigned_ds_division_code,
     sla_due_at, correlation_id)
VALUES (:id, :public_ref, :household_id, :subject_type, CAST(:subject_id AS uuid),
        :channel, :raised_at, CAST(:description AS jsonb), :status,
        CAST(:assigned_ds_division_id AS uuid), :assigned_ds_division_code,
        :sla_due_at, :correlation_id)
RETURNING id::text, public_ref, status, raised_at, sla_due_at
"""

_GET_GRIEVANCE = """
SELECT id::text, public_ref, household_id::text, subject_type, subject_id::text,
       channel, raised_at, description, status, assigned_ds_division_code,
       sla_due_at, resolved_at, resolution, correlation_id
FROM aid.grievance
WHERE id = :grievance_id
"""

_LIST_GRIEVANCES = """
SELECT id::text, public_ref, household_id::text, subject_type, subject_id::text,
       channel, raised_at, status, assigned_ds_division_code, sla_due_at, resolved_at,
       (status NOT IN ('RESOLVED','REJECTED') AND sla_due_at < now()) AS sla_breached
FROM aid.grievance
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:ds AS text) IS NULL
       OR assigned_ds_division_code LIKE CAST(:ds AS text) || '%')
  AND (CAST(:household_id AS uuid) IS NULL
       OR household_id = CAST(:household_id AS uuid))
ORDER BY sla_due_at
LIMIT :limit OFFSET :offset
"""

_ASSIGN_GRIEVANCE = """
UPDATE aid.grievance
SET status = :status,
    assigned_ds_division_id = CAST(:division_id AS uuid),
    assigned_ds_division_code = :division_code
WHERE id = :grievance_id
RETURNING id::text, public_ref, status, assigned_ds_division_code
"""

_RESOLVE_GRIEVANCE = """
UPDATE aid.grievance
SET status = :status,
    resolution = CAST(:resolution AS jsonb),
    resolved_at = now()
WHERE id = :grievance_id
  AND status NOT IN ('RESOLVED', 'REJECTED')
RETURNING id::text, public_ref, household_id::text, status, resolution, resolved_at,
          raised_at, sla_due_at
"""

_SET_GRIEVANCE_STATUS = """
UPDATE aid.grievance
SET status = :status
WHERE id = :grievance_id
  AND status NOT IN ('RESOLVED', 'REJECTED')
RETURNING id::text, public_ref, status
"""


async def insert_grievance(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_GRIEVANCE), values)
    return dict(result.mappings().one())


async def get_grievance(session: AsyncSession, grievance_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_GRIEVANCE), {"grievance_id": grievance_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_grievances(
    session: AsyncSession,
    *,
    status: str | None = None,
    ds: str | None = None,
    household_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_GRIEVANCES),
        {
            "status": status,
            "ds": ds,
            "household_id": household_id,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]


async def assign_grievance(
    session: AsyncSession,
    *,
    grievance_id: UUID,
    division_id: UUID | None,
    division_code: str,
    status: str,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_ASSIGN_GRIEVANCE),
        {
            "grievance_id": grievance_id,
            "division_id": division_id,
            "division_code": division_code,
            "status": status,
        },
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def resolve_grievance(
    session: AsyncSession, *, grievance_id: UUID, status: str, resolution: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_RESOLVE_GRIEVANCE),
        {"grievance_id": grievance_id, "status": status, "resolution": resolution},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def set_grievance_status(
    session: AsyncSession, *, grievance_id: UUID, status: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_SET_GRIEVANCE_STATUS), {"grievance_id": grievance_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


# --------------------------------------------------------------------------------------
# Anomaly flags
# --------------------------------------------------------------------------------------

_LIST_ANOMALIES = """
SELECT id::text, subject_type, subject_id::text, detector, detector_version,
       score, rationale, raised_at, disposition, disposed_by::text, disposed_at,
       disposition_note
FROM aid.anomaly_flag
WHERE (CAST(:disposition AS text) IS NULL OR disposition = CAST(:disposition AS text))
  AND (CAST(:subject_type AS text) IS NULL OR subject_type = CAST(:subject_type AS text))
ORDER BY raised_at DESC
LIMIT :limit OFFSET :offset
"""

_GET_ANOMALY = """
SELECT id::text, subject_type, subject_id::text, detector, detector_version,
       score, rationale, raised_at, disposition, disposed_by::text, disposed_at,
       disposition_note
FROM aid.anomaly_flag
WHERE id = :anomaly_id
"""

_DISPOSE_ANOMALY = """
UPDATE aid.anomaly_flag
SET disposition = :disposition,
    disposed_by = :disposed_by,
    disposed_at = now(),
    disposition_note = :note
WHERE id = :anomaly_id AND disposition = 'OPEN'
RETURNING id::text, subject_type, disposition, disposed_at
"""


async def list_anomalies(
    session: AsyncSession,
    *,
    disposition: str | None = None,
    subject_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_ANOMALIES),
        {
            "disposition": disposition,
            "subject_type": subject_type,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]


async def get_anomaly(session: AsyncSession, anomaly_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_ANOMALY), {"anomaly_id": anomaly_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def dispose_anomaly(
    session: AsyncSession, *, anomaly_id: UUID, disposition: str, disposed_by: UUID, note: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_DISPOSE_ANOMALY),
        {
            "anomaly_id": anomaly_id,
            "disposition": disposition,
            "disposed_by": disposed_by,
            "note": note,
        },
    )
    row = result.mappings().first()
    return dict(row) if row else None
