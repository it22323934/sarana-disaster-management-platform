"""Writing and reading audit entries.

Writing is a plain INSERT: the hash chain is a database trigger, so an entry is chained
whether it arrives through this function, through a migration, or through psql. That is
the point of putting the chain in the database rather than in the application.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.domain.ids import uuid7

_INSERT_SQL = """
INSERT INTO audit.audit_entry (
    id, actor_type, actor_id, agent_name, action,
    subject_type, subject_id, correlation_id, langgraph_thread_id,
    before, after
) VALUES (
    :id, :actor_type, :actor_id, :agent_name, :action,
    :subject_type, :subject_id, :correlation_id, :langgraph_thread_id,
    CAST(:before AS jsonb), CAST(:after AS jsonb)
)
RETURNING id::text, seq, occurred_at, entry_hash
"""

_SEARCH_SQL = """
SELECT id::text, seq, occurred_at, actor_type, actor_id::text, agent_name,
       action, subject_type, subject_id, correlation_id, langgraph_thread_id,
       before, after, prev_hash, entry_hash
FROM audit.audit_entry
WHERE (CAST(:subject_type AS text) IS NULL OR subject_type = CAST(:subject_type AS text))
  AND (CAST(:subject_id AS text) IS NULL OR subject_id = CAST(:subject_id AS text))
  AND (CAST(:actor_id AS uuid) IS NULL OR actor_id = CAST(:actor_id AS uuid))
  AND (CAST(:correlation_id AS text) IS NULL OR correlation_id = CAST(:correlation_id AS text))
  AND (CAST(:from_time AS timestamptz) IS NULL OR occurred_at >= CAST(:from_time AS timestamptz))
  AND (CAST(:to_time AS timestamptz) IS NULL OR occurred_at <= CAST(:to_time AS timestamptz))
ORDER BY seq DESC
LIMIT :limit OFFSET :offset
"""


async def write_entry(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    subject_type: str,
    subject_id: str,
    correlation_id: str,
    actor_id: UUID | None = None,
    agent_name: str | None = None,
    langgraph_thread_id: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> dict[str, Any]:
    """Append one entry. The trigger fills prev_hash and entry_hash.

    `before` and `after` arrive already serialised and already redacted. Redaction is the
    caller's job because only the caller knows which of its fields are personal data, and
    an audit entry must be enough to reconstruct a decision without becoming a second copy
    of the data behind it.
    """
    result = await session.execute(
        text(_INSERT_SQL),
        {
            "id": uuid7(),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "agent_name": agent_name,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "correlation_id": correlation_id,
            "langgraph_thread_id": langgraph_thread_id,
            "before": before,
            "after": after,
        },
    )
    return dict(result.mappings().one())


async def search_entries(
    session: AsyncSession,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    actor_id: UUID | None = None,
    correlation_id: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Entries matching a filter, newest first."""
    result = await session.execute(
        text(_SEARCH_SQL),
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "from_time": from_time,
            "to_time": to_time,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]
