"""The envelope every SARANA event travels in.

Event types follow `sarana.{domain}.{noun}.{verb}`, e.g. `sarana.incident.report.received`.

Two fields carry the weight here. `correlation_id` survives the whole chain from a raw
citizen report to a disbursement and is never regenerated - it is what lets an auditor ask
"what happened to this person's report" and get an answer. `causation_id` records which
single event produced this one, so the chain is a tree rather than a pile.

`trace_context` carries W3C traceparent, so a replayed event lands in the same trace as
the original rather than appearing as an orphan three weeks later.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sarana_shared.domain.ids import ensure_correlation_uuid, uuid7
from sarana_shared.domain.time import utc_now

EVENT_TYPE_PATTERN: Final = re.compile(
    r"^sarana\.[a-z0-9]+(?:_[a-z0-9]+)*\.[a-z0-9_]+(?:\.[a-z0-9_]+)?$"
)


class EventEnvelope(BaseModel):
    """A published domain event.

    Immutable once constructed. The payload is a JSON-serialisable dict; the concrete
    Pydantic model for a given type lives in the registry and is applied on read, so a
    consumer that does not know a type can still forward, archive or replay it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid7)
    event_type: str = Field(description="sarana.{domain}.{noun}.{verb}")
    schema_version: int = Field(default=1, ge=1)

    correlation_id: UUID = Field(default_factory=ensure_correlation_uuid)
    causation_id: UUID | None = Field(
        default=None, description="event_id of the event that directly caused this one"
    )

    occurred_at: datetime = Field(default_factory=utc_now)
    producer: str = Field(description="Service or agent that published this event")
    subject: str | None = Field(
        default=None, description="Primary entity this event is about, e.g. an incident ref"
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    # W3C Trace Context. Carried so a replay rejoins the trace of the original rather than
    # appearing as an orphan span weeks later.
    trace_context: dict[str, str] = Field(default_factory=dict)

    # Set only on a replayed envelope. Consumers that are not side-effect free refuse an
    # envelope carrying these, which is what stops a replay re-sending an SMS or
    # re-releasing money.
    replay_of: UUID | None = Field(default=None)
    replayed_at: datetime | None = Field(default=None)

    @field_validator("event_type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if not EVENT_TYPE_PATTERN.match(value):
            raise ValueError(
                f"event type {value!r} must match sarana.{{domain}}.{{noun}}.{{verb}}, "
                "all lowercase, e.g. sarana.incident.report.received"
            )
        return value

    @model_validator(mode="after")
    def _check_times(self) -> Self:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if (self.replay_of is None) != (self.replayed_at is None):
            raise ValueError(
                "replay_of and replayed_at are set together or not at all; one without "
                "the other would let a replayed event pass as an original"
            )
        return self

    @property
    def domain(self) -> str:
        """The domain segment, e.g. `incident`."""
        return self.event_type.split(".")[1]

    @property
    def is_replay(self) -> bool:
        """Whether this envelope is a replay of an earlier event."""
        return self.replay_of is not None

    @property
    def partition_key(self) -> str:
        """What ordering is guaranteed on.

        Per correlation ID only, never globally. Every event about one citizen's report
        arrives in order; two unrelated reports have no order between them and a consumer
        that assumes otherwise is wrong.
        """
        return str(self.correlation_id)

    def caused(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        producer: str,
        subject: str | None = None,
        schema_version: int = 1,
    ) -> EventEnvelope:
        """Build a follow-on event that keeps the chain intact.

        Carries the correlation ID and trace context forward and records this event as
        the cause, which is what makes an agent run reconstructable from the log alone.
        """
        return EventEnvelope(
            event_type=event_type,
            schema_version=schema_version,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            producer=producer,
            subject=subject if subject is not None else self.subject,
            payload=payload,
            trace_context=dict(self.trace_context),
        )

    def as_replay(self, *, at: datetime | None = None) -> EventEnvelope:
        """Return a copy marked as a replay of this event.

        A new `event_id` so idempotency records stay distinct, the original preserved in
        `replay_of` so a consumer can refuse it and an operator can trace it back.
        """
        return self.model_copy(
            update={
                "event_id": uuid7(),
                "replay_of": self.event_id,
                "replayed_at": at or utc_now(),
            }
        )
