"""Replay: re-delivering history, safely enough to do it in production.

Replay is the guarantee ADR-003 keeps from the Kafka proposal - "any failed agent task can
be safely retried from the last known event" - and the word doing the work is *safely*.

Three rules make it safe:

  1. A replayed envelope is marked. `replay_of` and `replayed_at` are set, so nothing
     downstream can mistake it for a first delivery.
  2. Consumers with real-world side effects refuse it. An SMS consumer replaying a
     cyclone warning three weeks late is worse than whatever the replay was fixing.
  3. It is scoped. Time window, event types, one target group. There is no call that
     replays everything to everyone, because that mistake is not recoverable on a
     platform that sends messages and moves money.

One replay runs at a time. Two overlapping replays would make the delivered counts
meaningless and could double-deliver to the same group.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import structlog

from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import EventBus, ReplayHandle

_log = structlog.get_logger(__name__)

# A window wider than this is almost always a mistake - someone meant days and typed
# months. Refusing it costs an operator one retry with an explicit override; allowing it
# costs a re-delivery of an entire disaster.
MAX_WINDOW: Final = timedelta(days=30)


class ReplayRefused(Exception):
    """The replay was not started, and why."""


class ReplayInProgress(ReplayRefused):
    """Another replay is already running."""

    def __init__(self, running: ReplayHandle) -> None:
        super().__init__(
            f"a replay into {running.target_group} started at "
            f"{running.started_at.isoformat()} is still running. One at a time: two "
            "overlapping replays can double-deliver to the same group."
        )
        self.running = running


@dataclass
class ReplayCoordinator:
    """Starts replays, one at a time, and remembers what they did.

    Deliberately stateful and deliberately single-slot. The constraint is the safety
    feature: an operator running a replay during an incident should have to notice that
    one is already going rather than quietly stacking a second.
    """

    bus: EventBus
    _running: ReplayHandle | None = None
    _history: list[ReplayHandle] = None  # type: ignore[assignment]  # set in __post_init__
    _lock: asyncio.Lock = None  # type: ignore[assignment]  # set in __post_init__

    def __post_init__(self) -> None:
        self._history = []
        self._lock = asyncio.Lock()

    @property
    def running(self) -> ReplayHandle | None:
        """The replay currently in flight, if any."""
        return self._running

    @property
    def history(self) -> list[ReplayHandle]:
        """Every replay this process has run, most recent last."""
        return list(self._history)

    async def start(
        self,
        *,
        since: datetime,
        until: datetime | None,
        event_types: tuple[str, ...],
        target_group: str,
        requested_by: str,
        allow_wide_window: bool = False,
    ) -> ReplayHandle:
        """Run one replay to completion.

        Raises:
            ReplayInProgress: if another replay is running.
            ReplayRefused: if the request is unscoped or the window is implausibly wide.
        """
        if not event_types:
            raise ReplayRefused(
                "a replay must name its event types. There is no replay-everything call: "
                "on a platform that sends SMS and moves money, that mistake is not "
                "recoverable."
            )
        if not target_group:
            raise ReplayRefused("a replay must name exactly one target consumer group")

        window = (until or utc_now()) - since
        if window > MAX_WINDOW and not allow_wide_window:
            raise ReplayRefused(
                f"a {window.days}-day window is wider than the {MAX_WINDOW.days}-day "
                "guard. If that is genuinely what you meant, pass allow_wide_window."
            )
        if window <= timedelta(0):
            raise ReplayRefused("the replay window ends before it begins")

        async with self._lock:
            if self._running is not None and self._running.is_running:
                raise ReplayInProgress(self._running)

            pending = ReplayHandle(
                replay_id=_new_replay_id(),
                target_group=target_group,
                event_types=event_types,
                since=since,
                until=until,
                requested_by=requested_by,
                started_at=utc_now(),
            )
            self._running = pending

        _log.info(
            "replay_started",
            replay_id=str(pending.replay_id),
            target_group=target_group,
            event_types=list(event_types),
            since=since.isoformat(),
            until=until.isoformat() if until else None,
            requested_by=requested_by,
        )

        try:
            handle = await self.bus.replay(
                since=since,
                until=until,
                event_types=event_types,
                target_group=target_group,
                requested_by=requested_by,
            )
        finally:
            self._running = None

        self._history.append(handle)
        _log.info(
            "replay_finished",
            replay_id=str(handle.replay_id),
            target_group=target_group,
            delivered=handle.delivered,
            refused=handle.refused,
        )
        return handle


def _new_replay_id() -> UUID:
    from sarana_shared.domain.ids import uuid7

    return uuid7()
