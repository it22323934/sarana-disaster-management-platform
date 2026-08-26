"""The event envelope every SARANA event travels in.

Event names follow `sarana.{domain}.{noun}.{past-tense-verb}`, e.g.
`sarana.incident.report.received`. The `correlation_id` survives the whole chain from a
raw citizen report to a disbursement - never break it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sarana_shared.domain.ids import ensure_correlation_id, uuid7
from sarana_shared.domain.time import utc_now

EVENT_TYPE_PATTERN: Final = re.compile(
    r"^sarana\.[a-z0-9]+(?:_[a-z0-9]+)*\.[a-z0-9_]+\.[a-z0-9_]+$"
)

SCHEMA_VERSION_PATTERN: Final = re.compile(r"^\d+$")


class EventEnvelope(BaseModel):
    """A published domain event.

    Immutable once constructed. The payload is a JSON-serialisable dict; the concrete
    Pydantic model for a given `type` lives in the registry and is applied on read, so a
    consumer that does not know a type can still forward or archive the event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid7)
    type: str = Field(description="sarana.{domain}.{noun}.{past-tense-verb}")
    schema_version: int = Field(default=1, ge=1)
    correlation_id: str = Field(default_factory=ensure_correlation_id)
    causation_id: UUID | None = Field(
        default=None, description="event_id of the event that directly caused this one"
    )
    occurred_at: datetime = Field(default_factory=utc_now)
    source: str = Field(description="Service or agent that published this event")
    subject: str | None = Field(
        default=None, description="Primary entity this event is about, e.g. an incident ID"
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if not EVENT_TYPE_PATTERN.match(value):
            raise ValueError(
                f"event type {value!r} must match sarana.{{domain}}.{{noun}}.{{verb}}, "
                "all lowercase, e.g. sarana.incident.report.received"
            )
        return value

    @model_validator(mode="after")
    def _check_occurred_at(self) -> Self:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return self

    @property
    def domain(self) -> str:
        """The domain segment, e.g. `incident`."""
        return self.type.split(".")[1]

    def caused(
        self,
        type: str,
        payload: dict[str, Any],
        *,
        source: str,
        subject: str | None = None,
        schema_version: int = 1,
    ) -> EventEnvelope:
        """Build a follow-on event that keeps the chain intact.

        Carries the correlation ID forward and records this event as the cause, which is
        what makes an agent run reconstructable from the log alone.
        """
        return EventEnvelope(
            type=type,
            schema_version=schema_version,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            source=source,
            subject=subject if subject is not None else self.subject,
            payload=payload,
        )
