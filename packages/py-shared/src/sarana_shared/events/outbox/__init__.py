"""The transactional outbox: the source of truth for every event SARANA emits.

ADR-003. A service writes its domain row and its outbox row in the same transaction, so an
event can never describe a state change that did not commit, and a commit can never fail
to produce its event.

If the broker loses a message, the outbox still has it. If a consumer processes twice,
`processed_event` makes the second one a no-op. Between them there is no window in which
work happens without a record, or a record exists without the work.
"""

from sarana_shared.events.outbox.publisher import OutboxPublisher
from sarana_shared.events.outbox.table import (
    MAX_PUBLISH_ATTEMPTS,
    OUTBOX_SCHEMA,
    OutboxEventBase,
    enqueue,
    make_outbox_model,
    reset_stuck_events,
    stuck_event_count,
)
from sarana_shared.events.outbox.worker import OutboxWorker

__all__ = [
    "MAX_PUBLISH_ATTEMPTS",
    "OUTBOX_SCHEMA",
    "OutboxEventBase",
    "OutboxPublisher",
    "OutboxWorker",
    "enqueue",
    "make_outbox_model",
    "reset_stuck_events",
    "stuck_event_count",
]
