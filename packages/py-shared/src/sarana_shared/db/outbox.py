"""Transactional outbox table + a minimal publisher, scoped to what
docs/build-prompts/03-monorepo-scaffold.md asks for.

The outbox is the source of truth for "what did this service decide to publish" — a
service writes its domain row and an OutboxEntry in the same transaction, so a crash
between "decided" and "published" is impossible. docs/build-prompts/06-event-bus.md
replaces this with a fuller outbox/ subpackage (table.py, publisher.py, worker.py) that
polls with FOR UPDATE SKIP LOCKED and pushes to Redis Streams / EventBridge — this file
is the table definition and the same write-path helper that both the scaffold and that
later build depend on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from sarana_shared.db.base import Base, UUIDPrimaryKeyMixin
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import now_utc
from sarana_shared.events.envelope import EventEnvelope


class OutboxEntry(Base, UUIDPrimaryKeyMixin):
    """One row per event a service has decided to publish. `published_at` is set by the
    publisher once the bus has accepted it — never by the service that wrote the row."""

    __tablename__ = "outbox_entry"
    __table_args__ = (Index("ix_outbox_entry_unpublished", "published_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    event_type: Mapped[str] = mapped_column(String(200))
    correlation_id: Mapped[uuid.UUID]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    def to_envelope(self, *, producer: str) -> EventEnvelope:
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type,
            correlation_id=self.correlation_id,
            occurred_at=self.occurred_at,
            producer=producer,
            payload=self.payload,
        )


async def write_outbox_entry(
    session: AsyncSession,
    *,
    event_type: str,
    correlation_id: uuid.UUID,
    payload: dict[str, Any],
) -> OutboxEntry:
    """Call this in the SAME transaction as the domain write it's reporting on — never
    call it standalone, or the atomicity guarantee the whole outbox pattern exists for is
    gone. No `causation_id` column yet — the file 06 outbox rebuild adds that, along with
    the polling publisher and replay support.
    """
    entry = OutboxEntry(
        event_id=uuid7(),
        event_type=event_type,
        correlation_id=correlation_id,
        payload=payload,
        occurred_at=now_utc(),
    )
    session.add(entry)
    await session.flush()
    return entry
