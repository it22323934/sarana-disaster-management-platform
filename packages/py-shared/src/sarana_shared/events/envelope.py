"""EventEnvelope — the one shape every event on the bus takes, per
docs/build-prompts/06-event-bus.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import now_utc


class EventEnvelope(BaseModel):
    event_id: UUID = Field(default_factory=uuid7)
    event_type: str  # "sarana.{domain}.{noun}.{past-tense-verb}"
    schema_version: int = 1
    correlation_id: UUID  # survives raw report -> disbursement; never regenerated mid-chain
    causation_id: UUID | None = None  # the event_id that caused this one, if any
    occurred_at: datetime = Field(default_factory=now_utc)
    producer: str  # service or agent name that emitted this event
    payload: dict[str, Any]
    trace_context: dict[str, Any] = Field(default_factory=dict)  # W3C traceparent etc.

    # Set only on a replayed envelope (docs/build-prompts/06-event-bus.md "Replay").
    replay_of: UUID | None = None
    replayed_at: datetime | None = None

    def is_replay(self) -> bool:
        return self.replay_of is not None
