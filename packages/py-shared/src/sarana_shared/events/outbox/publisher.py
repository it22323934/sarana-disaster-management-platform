"""Moves committed outbox rows onto the bus.

Claims rows with `FOR UPDATE SKIP LOCKED`, so several replicas run concurrently without
double-publishing and without blocking each other.

The crash-safety property is the one that matters: a row is marked published only after
its publish returns. Kill the process mid-batch and the rows it had not yet acknowledged
are still unpublished, so the next run picks them up. Nothing is lost, and the duplicate
that a redelivery might produce is absorbed by `processed_event` on the consumer side.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sarana_shared.db.session import session_scope
from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import EventBus
from sarana_shared.events.outbox.table import MAX_PUBLISH_ATTEMPTS, OutboxEventBase

_log = structlog.get_logger(__name__)


class OutboxPublisher:
    """Drains one service's outbox onto the bus."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        model: type[OutboxEventBase],
        *,
        batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._model = model
        self._batch_size = batch_size

    @property
    def table_name(self) -> str:
        """Which outbox this publisher drains. Used in log lines and metrics."""
        return str(self._model.__tablename__)

    async def drain_once(self) -> int:
        """Publish one batch. Returns the number of events published.

        Each row is marked published individually after its own successful publish, so a
        crash part-way through a batch replays only what was not yet acknowledged.
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
                        event_type=row.event_type,
                        correlation_id=str(row.correlation_id),
                        attempts=row.attempts,
                        error=row.last_error,
                    )
                    continue

                row.published_at = utc_now()
                row.last_error = None
                published += 1

        return published

    async def drain(self, *, max_batches: int = 100) -> int:
        """Publish until the outbox is empty or the batch limit is reached.

        Bounded so a caller draining synchronously - a test, or a shutdown hook - cannot
        spin forever against a publisher that is failing every row.
        """
        total = 0
        for _ in range(max_batches):
            count = await self.drain_once()
            if count == 0:
                return total
            total += count
        return total
