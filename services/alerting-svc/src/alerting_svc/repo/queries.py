"""Reads and writes over the alerting schema.

Plain SQL returning dictionaries. Every parameter compared against NULL is cast
explicitly: asyncpg prepares statements and cannot infer the type of a bare parameter in
`:x IS NULL`, which fails at runtime rather than at import.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.domain.ids import uuid7

_GET_TEMPLATE_BY_CODE = """
SELECT id::text, code, hazard_type, severity, urgency, certainty, body,
       reviewed_by_si::text, reviewed_by_ta::text, reviewed_at, version, status
FROM alerting.alert_template
WHERE code = :code AND status = 'PUBLISHED'
ORDER BY version DESC
LIMIT 1
"""

_GET_TEMPLATE = """
SELECT id::text, code, hazard_type, severity, urgency, certainty, body,
       reviewed_by_si::text, reviewed_by_ta::text, reviewed_at, version, status
FROM alerting.alert_template
WHERE id = :template_id
"""

_LIST_TEMPLATES = """
SELECT id::text, code, hazard_type, severity, urgency, certainty, body,
       reviewed_by_si::text, reviewed_by_ta::text, reviewed_at, version, status
FROM alerting.alert_template
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:hazard AS text) IS NULL OR hazard_type = CAST(:hazard AS text))
ORDER BY code, version DESC
LIMIT :limit OFFSET :offset
"""

_INSERT_TEMPLATE = """
INSERT INTO alerting.alert_template
    (id, code, hazard_type, severity, urgency, certainty, body, status)
VALUES (:id, :code, :hazard_type, :severity, :urgency, :certainty,
        CAST(:body AS jsonb), 'DRAFT')
RETURNING id::text, code, status, version
"""

# Both signatures and the timestamp move together. The CHECK constraint refuses
# NATIVE_REVIEWED without all three, so a partial review can never be stored.
_RECORD_REVIEW = """
UPDATE alerting.alert_template
SET reviewed_by_si = COALESCE(CAST(:reviewer_si AS uuid), reviewed_by_si),
    reviewed_by_ta = COALESCE(CAST(:reviewer_ta AS uuid), reviewed_by_ta),
    reviewed_at = CASE
        WHEN COALESCE(CAST(:reviewer_si AS uuid), reviewed_by_si) IS NOT NULL
         AND COALESCE(CAST(:reviewer_ta AS uuid), reviewed_by_ta) IS NOT NULL
        THEN now() ELSE reviewed_at END,
    status = CASE
        WHEN COALESCE(CAST(:reviewer_si AS uuid), reviewed_by_si) IS NOT NULL
         AND COALESCE(CAST(:reviewer_ta AS uuid), reviewed_by_ta) IS NOT NULL
        THEN 'NATIVE_REVIEWED' ELSE status END
WHERE id = :template_id AND status IN ('DRAFT', 'NATIVE_REVIEWED')
RETURNING id::text, status, reviewed_by_si::text, reviewed_by_ta::text, reviewed_at
"""

_PUBLISH_TEMPLATE = """
UPDATE alerting.alert_template
SET status = 'PUBLISHED'
WHERE id = :template_id
  AND status = 'NATIVE_REVIEWED'
  AND reviewed_by_si IS NOT NULL
  AND reviewed_by_ta IS NOT NULL
RETURNING id::text, code, status
"""

_INSERT_ALERT = """
INSERT INTO alerting.alert (
    id, hazard_event_id, template_id, cap_identifier, cap_xml,
    headline, description, instruction, severity, urgency, certainty,
    effective_at, expires_at, area_gn_division_ids,
    requires_human_signoff, status, correlation_id
) VALUES (
    :id, :hazard_event_id, CAST(:template_id AS uuid), :cap_identifier, CAST(:cap_xml AS text),
    CAST(:headline AS jsonb), CAST(:description AS jsonb), CAST(:instruction AS jsonb),
    :severity, :urgency, :certainty,
    CAST(:effective_at AS timestamptz), CAST(:expires_at AS timestamptz),
    CAST(:area_gn_division_ids AS uuid[]),
    :requires_human_signoff, :status, :correlation_id
)
RETURNING id::text, cap_identifier, status, requires_human_signoff
"""

_GET_ALERT = """
SELECT id::text, hazard_event_id::text, template_id::text, cap_identifier, cap_xml,
       headline, description, instruction, severity, urgency, certainty,
       effective_at, expires_at, area_gn_division_ids,
       requires_human_signoff, signed_off_by::text, signed_off_at, status,
       correlation_id, created_at
FROM alerting.alert
WHERE id = :alert_id
"""

_LIST_ALERTS = """
SELECT id::text, cap_identifier, headline, severity, urgency, status,
       effective_at, expires_at, requires_human_signoff, created_at
FROM alerting.alert
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset
"""

_LIST_DISPATCHED = """
SELECT id::text, cap_identifier, headline, created_at
FROM alerting.alert
WHERE status = 'DISPATCHED'
ORDER BY created_at DESC
LIMIT :limit
"""

# The only writer of a sign-off. The CHECK constraint refuses DISPATCHING or DISPATCHED
# for a free-text alert without one, so this statement and that constraint are the two
# halves of the soft third gate.
_SIGN_OFF_ALERT = """
UPDATE alerting.alert
SET signed_off_by = :approver_id, signed_off_at = now()
WHERE id = :alert_id AND signed_off_by IS NULL AND status = 'PENDING_SIGNOFF'
RETURNING id::text, status, signed_off_by::text, signed_off_at
"""

_SET_ALERT_STATUS = """
UPDATE alerting.alert
SET status = :status, cap_xml = COALESCE(CAST(:cap_xml AS text), cap_xml)
WHERE id = :alert_id
RETURNING id::text, status
"""

_INSERT_DISPATCH = """
INSERT INTO alerting.alert_dispatch (id, alert_id, channel, target_count, started_at, status)
VALUES (:id, :alert_id, :channel, :target_count, now(), :status)
RETURNING id::text, channel, target_count, status
"""

_COMPLETE_DISPATCH = """
UPDATE alerting.alert_dispatch
SET completed_at = now(), status = :status
WHERE id = :dispatch_id
RETURNING id::text, status
"""

_INSERT_RECEIPT = """
INSERT INTO alerting.delivery_receipt
    (id, dispatch_id, channel, target_ref_hash, language, status, provider_ref, failure_reason)
VALUES (:id, :dispatch_id, :channel, :target_ref_hash, :language, :status,
        CAST(:provider_ref AS text), CAST(:failure_reason AS text))
RETURNING id::text
"""

# A DLR upgrades a receipt the gateway has since confirmed. Matched on the provider's own
# reference because that is the only identifier the telco knows.
_APPLY_DLR = """
UPDATE alerting.delivery_receipt
SET status = :status, status_at = now(), failure_reason = CAST(:failure_reason AS text)
WHERE provider_ref = :provider_ref
RETURNING id::text, dispatch_id::text, status
"""

_DELIVERY_BY_ALERT = """
SELECT r.channel, r.language, r.status, r.target_ref_hash
FROM alerting.delivery_receipt r
JOIN alerting.alert_dispatch d ON d.id = r.dispatch_id
WHERE d.alert_id = :alert_id
"""

_DISPATCHES_BY_ALERT = """
SELECT id::text, channel, target_count, status, started_at, completed_at
FROM alerting.alert_dispatch
WHERE alert_id = :alert_id
ORDER BY channel
"""


async def get_published_template(session: AsyncSession, code: str) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_TEMPLATE_BY_CODE), {"code": code})
    row = result.mappings().first()
    return dict(row) if row else None


async def get_template(session: AsyncSession, template_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_TEMPLATE), {"template_id": template_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_templates(
    session: AsyncSession,
    *,
    status: str | None = None,
    hazard: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_TEMPLATES),
        {"status": status, "hazard": hazard, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings()]


async def insert_template(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_TEMPLATE), {"id": uuid7(), **values})
    return dict(result.mappings().one())


async def record_review(
    session: AsyncSession,
    template_id: UUID,
    *,
    reviewer_si: UUID | None = None,
    reviewer_ta: UUID | None = None,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_RECORD_REVIEW),
        {"template_id": template_id, "reviewer_si": reviewer_si, "reviewer_ta": reviewer_ta},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def publish_template(session: AsyncSession, template_id: UUID) -> dict[str, Any] | None:
    """Publish, or return None if the review is incomplete.

    The predicate does the refusing rather than the application: a template that reaches
    PUBLISHED unreviewed is a wrong message sent to a whole district.
    """
    result = await session.execute(text(_PUBLISH_TEMPLATE), {"template_id": template_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_alert(session: AsyncSession, **values: Any) -> dict[str, Any]:
    result = await session.execute(text(_INSERT_ALERT), {"id": uuid7(), **values})
    return dict(result.mappings().one())


async def get_alert(session: AsyncSession, alert_id: UUID) -> dict[str, Any] | None:
    result = await session.execute(text(_GET_ALERT), {"alert_id": alert_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_alerts(
    session: AsyncSession, *, status: str | None = None, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(_LIST_ALERTS), {"status": status, "limit": limit, "offset": offset}
    )
    return [dict(row) for row in result.mappings()]


async def list_dispatched(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    result = await session.execute(text(_LIST_DISPATCHED), {"limit": limit})
    return [dict(row) for row in result.mappings()]


async def sign_off_alert(
    session: AsyncSession, alert_id: UUID, approver_id: UUID
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_SIGN_OFF_ALERT), {"alert_id": alert_id, "approver_id": approver_id}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def set_alert_status(
    session: AsyncSession, alert_id: UUID, status: str, *, cap_xml: str | None = None
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_SET_ALERT_STATUS),
        {"alert_id": alert_id, "status": status, "cap_xml": cap_xml},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_dispatch(
    session: AsyncSession,
    *,
    alert_id: UUID,
    channel: str,
    target_count: int,
    status: str = "SENDING",
) -> dict[str, Any]:
    result = await session.execute(
        text(_INSERT_DISPATCH),
        {
            "id": uuid7(),
            "alert_id": alert_id,
            "channel": channel,
            "target_count": target_count,
            "status": status,
        },
    )
    return dict(result.mappings().one())


async def complete_dispatch(
    session: AsyncSession, dispatch_id: UUID, status: str
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_COMPLETE_DISPATCH), {"dispatch_id": dispatch_id, "status": status}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def insert_receipt(session: AsyncSession, **values: Any) -> None:
    await session.execute(text(_INSERT_RECEIPT), {"id": uuid7(), **values})


async def apply_dlr(
    session: AsyncSession,
    *,
    provider_ref: str,
    status: str,
    failure_reason: str | None = None,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(_APPLY_DLR),
        {"provider_ref": provider_ref, "status": status, "failure_reason": failure_reason},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def delivery_rows(session: AsyncSession, alert_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(text(_DELIVERY_BY_ALERT), {"alert_id": alert_id})
    return [dict(row) for row in result.mappings()]


async def dispatches_for(session: AsyncSession, alert_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(text(_DISPATCHES_BY_ALERT), {"alert_id": alert_id})
    return [dict(row) for row in result.mappings()]
