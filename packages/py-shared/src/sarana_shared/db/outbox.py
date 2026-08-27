"""The transactional outbox - the source of truth for every event SARANA emits.

ADR-003. A service writes its domain row and its outbox row in the same transaction, so
an event can never describe a state change that did not commit, and a commit can never
fail to produce its event. A relay then moves committed rows onto the bus.

Each service owns its own table in schema `outbox`, built by `make_outbox_model`. One
shared table would put every service's outbox inside one service's migration chain, so a
service could not create its own outbox without depending on another service having
migrated first. Separate tables also keep six relays off one row lock during a surge.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import structlog
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from sarana_shared.db.base import Base
from sarana_shared.db.session import session_scope
from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import EventBus
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)

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
    type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_envelope(self) -> EventEnvelope:
        """Rebuild the envelope for publication."""
        return EventEnvelope(
            event_id=self.event_id,
            type=self.type,
            schema_version=self.schema_version,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            occurred_at=self.occurred_at,
            source=self.source,
            subject=self.subject,
            payload=self.payload,
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
                # The relay only ever asks for unpublished rows in creation order, so
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
    session: AsyncSession, model: type[OutboxEventBase], event: EventEnvelope
) -> OutboxEventBase:
    """Add an event to the outbox inside the caller's transaction.

    Does not commit. The caller commits the domain write and this row together - that
    single commit is the whole point of the pattern.
    """
    row = model(
        event_id=event.event_id,
        type=event.type,
        schema_version=event.schema_version,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        source=event.source,
        subject=event.subject,
        payload=event.payload,
        occurred_at=event.occurred_at,
    )
    session.add(row)
    return row


class OutboxRelay:
    """Moves committed outbox rows onto the event bus.

    Runs as a background task inside each service's lifespan, over that service's own
    outbox table. Claims rows with `FOR UPDATE SKIP LOCKED`, so several replicas can run
    concurrently without double-publishing and without blocking each other.

    Delivery is at-least-once. Consumers deduplicate on `event_id`, which is why the bus
    contract requires `publish` to be idempotent on it.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        model: type[OutboxEventBase],
        *,
        batch_size: int = 100,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._model = model
        self._batch_size = batch_size
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None

    async def drain_once(self) -> int:
        """Publish one batch. Returns the number of events published.

        A row is marked published only after its publish succeeds, so a crash mid-batch
        replays only what was not yet acknowledged.
        """
        published = 0
        async with session_scope(self._session_factory) as session:
            claimed = (
                (
                    await session.execute(
                        select(self._model)
                        .where(
                            self._model.published_at.is_(None),
                            self._model.attempts < MAX_PUBLISH_ATTEMPTS,
                        )
                        .order_by(self._model.created_at)
                        .limit(self._batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )

            for row in claimed:
                try:
                    await self._bus.publish(row.to_envelope())
                except Exception as exc:  # noqa: BLE001 - recorded on the row, then retried
                    row.attempts += 1
                    row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                    _log.warning(
                        "outbox_publish_failed",
                        event_id=str(row.event_id),
                        event_type=row.type,
                        correlation_id=row.correlation_id,
                        attempts=row.attempts,
                        error=row.last_error,
                    )
                    continue

                row.published_at = utc_now()
                row.last_error = None
                published += 1

        return published

    async def run(self) -> None:
        """Poll until cancelled. Backs off only when there was nothing to publish."""
        _log.info("outbox_relay_started", table=self._model.__tablename__)
        while True:
            try:
                count = await self.drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the relay must outlive a bad batch
                _log.exception("outbox_relay_batch_failed")
                count = 0
            if count == 0:
                await asyncio.sleep(self._poll_interval_s)

    def start(self) -> None:
        """Launch the relay as a background task."""
        if self._task is not None:
            raise RuntimeError("outbox relay is already running")
        self._task = asyncio.create_task(self.run(), name="sarana-outbox-relay")

    async def stop(self) -> None:
        """Cancel the relay and wait for it to finish."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            _log.info("outbox_relay_stopped")


async def stuck_event_count(session: AsyncSession, model: type[OutboxEventBase]) -> int:
    """How many events have exhausted their retries.

    Surfaced as a metric and on the operator console. A non-zero value means a state
    change committed and the rest of the platform never heard about it.
    """
    result = await session.execute(
        select(func.count())
        .select_from(model)
        .where(
            model.published_at.is_(None),
            model.attempts >= MAX_PUBLISH_ATTEMPTS,
        )
    )
    return int(result.scalar_one())


async def reset_stuck_events(session: AsyncSession, model: type[OutboxEventBase]) -> int:
    """Clear the attempt counter on exhausted rows so the relay retries them.

    Operator action, taken after the underlying cause is fixed. Never automatic.
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(model)
            .where(
                model.published_at.is_(None),
                model.attempts >= MAX_PUBLISH_ATTEMPTS,
            )
            .values(attempts=0, last_error=None)
        ),
    )
    return int(result.rowcount or 0)
