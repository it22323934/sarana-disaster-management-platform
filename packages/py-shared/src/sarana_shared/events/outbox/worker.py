"""The background task that runs a publisher on a loop.

Separated from the publisher so the draining logic can be driven directly by a test - and
by a shutdown hook - without a task, a sleep, or a race to reason about. The worker is
scheduling; the publisher is the work.
"""

from __future__ import annotations

import asyncio

import structlog

from sarana_shared.events.outbox.publisher import OutboxPublisher

_log = structlog.get_logger(__name__)


class OutboxWorker:
    """Runs an `OutboxPublisher` until cancelled."""

    def __init__(
        self,
        publisher: OutboxPublisher,
        *,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._publisher = publisher
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Poll until cancelled. Backs off only when there was nothing to publish."""
        _log.info("outbox_worker_started", table=self._publisher.table_name)
        while True:
            try:
                count = await self._publisher.drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the worker must outlive a bad batch
                _log.exception("outbox_worker_batch_failed", table=self._publisher.table_name)
                count = 0
            if count == 0:
                await asyncio.sleep(self._poll_interval_s)

    def start(self) -> None:
        """Launch the worker as a background task."""
        if self._task is not None:
            raise RuntimeError("this outbox worker is already running")
        self._task = asyncio.create_task(self.run(), name="sarana-outbox-worker")

    async def stop(self, *, drain: bool = True) -> None:
        """Cancel the worker, optionally draining what is left first.

        Draining on shutdown is not required for correctness - an undrained row is picked
        up by the next process to start - but it means a deploy does not leave events
        sitting for however long the new task takes to come up.
        """
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

        if drain:
            try:
                remaining = await self._publisher.drain()
                if remaining:
                    _log.info(
                        "outbox_drained_on_shutdown",
                        table=self._publisher.table_name,
                        published=remaining,
                    )
            except Exception:  # noqa: BLE001 - shutdown must not fail on a bad drain
                _log.exception("outbox_shutdown_drain_failed")

        _log.info("outbox_worker_stopped", table=self._publisher.table_name)

    @property
    def is_running(self) -> bool:
        """Whether the background task is live."""
        return self._task is not None and not self._task.done()
