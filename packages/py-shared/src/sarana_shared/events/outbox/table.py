"""The outbox table, and the model factory that builds one per service.

Each service owns its own table in schema `outbox`. One shared table would put every
service's outbox inside one service's migration chain, so a service could not create its
own outbox without another having migrated first. Separate tables also keep six publishers
off one row lock during a surge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    CursorResult,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from sarana_shared.db.base import Base
from sarana_shared.events.envelope import EventEnvelope

OUTBOX_SCHEMA = "outbox"

# After this many consecutive publish failures a row stops being retried and is left for
# an operator. It is never deleted - a stuck event is evidence, not noise.
MAX_PUBLISH_ATTEMPTS = 10


class OutboxEventBase(Base):
    """The columns every service's outbox table carries.

    Abstract: SQLAlchemy maps only the concrete subclasses `make_outbox_model` builds.
    Mirrors `EventEnvelope` field for field, so `to_envelope` is a straight copy with no
    reshaping to get wrong.
    """

    __abstract__ = True

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    producer: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trace_context: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_envelope(self) -> EventEnvelope:
        """Rebuild the envelope for publication."""
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type,
            schema_version=self.schema_version,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            occurred_at=self.occurred_at,
            producer=self.producer,
            subject=self.subject,
            payload=self.payload,
            trace_context=self.trace_context,
        )


def make_outbox_model(service_module: str) -> type[OutboxEventBase]:
    """Build the outbox model for one service, in schema `outbox`.

    Called once, at import time, from the service's `repo` package:

        OutboxEvent = make_outbox_model("incident_svc")

    Args:
        service_module: The service's Python module name, e.g. `incident_svc`. Becomes
            the table name `outbox.incident_svc_event`.
    """
    table_name = f"{service_module}_event"

    model = type(
        f"{''.join(part.title() for part in service_module.split('_'))}OutboxEvent",
        (OutboxEventBase,),
        {
            "__tablename__": table_name,
            "__table_args__": (
                # The publisher only ever asks for unpublished rows in creation order, so
                # the index covers exactly that and stays small however large the table
                # grows: published rows drop out of it.
                Index(
                    f"ix_{table_name}_unpublished",
                    "created_at",
                    postgresql_where=text("published_at IS NULL"),
                ),
                {"schema": OUTBOX_SCHEMA},
            ),
        },
    )
    return cast("type[OutboxEventBase]", model)


def enqueue(
    session: AsyncSession, model: type[OutboxEventBase], envelope: EventEnvelope
) -> OutboxEventBase:
    """Add an event to the outbox inside the caller's transaction.

    Does not commit. The caller commits the domain write and this row together - that
    single commit is the whole point of the pattern, and it is why a rolled-back
    transaction emits nothing.
    """
    row = model(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        schema_version=envelope.schema_version,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.causation_id,
        producer=envelope.producer,
        subject=envelope.subject,
        payload=envelope.payload,
        trace_context=envelope.trace_context,
        occurred_at=envelope.occurred_at,
    )
    session.add(row)
    return row


async def stuck_event_count(session: AsyncSession, model: type[OutboxEventBase]) -> int:
    """How many events have exhausted their retries.

    Surfaced as a metric and on the operator console. A non-zero value means a state
    change committed and the rest of the platform never heard about it.
    """
    result = await session.execute(
        select(func.count())
        .select_from(model)
        .where(model.published_at.is_(None), model.attempts >= MAX_PUBLISH_ATTEMPTS)
    )
    return int(result.scalar_one())


async def reset_stuck_events(session: AsyncSession, model: type[OutboxEventBase]) -> int:
    """Clear the attempt counter on exhausted rows so the publisher retries them.

    Operator action, taken after the underlying cause is fixed. Never automatic.
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(model)
            .where(model.published_at.is_(None), model.attempts >= MAX_PUBLISH_ATTEMPTS)
            .values(attempts=0, last_error=None)
        ),
    )
    return int(result.rowcount or 0)
