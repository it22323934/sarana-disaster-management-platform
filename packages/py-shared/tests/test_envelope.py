"""The envelope, and the two identifiers that make an event chain reconstructable."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sarana_shared.domain.ids import uuid7
from sarana_shared.events.envelope import EventEnvelope


def an_event(event_type: str = "sarana.incident.report.received") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="incident-svc",
        correlation_id=uuid7(),
        payload={"channel": "SMS"},
    )


def test_event_type_shape_is_enforced() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(event_type="IncidentReportReceived", producer="incident-svc")


def test_domain_is_read_from_the_type() -> None:
    assert an_event().domain == "incident"


def test_a_caused_event_keeps_the_chain_intact() -> None:
    """The chain from raw citizen report to disbursement is never broken."""
    received = an_event()

    verified = received.caused(
        "sarana.incident.verified", {"confidence": 0.91}, producer="agent-svc"
    )

    assert verified.correlation_id == received.correlation_id
    assert verified.causation_id == received.event_id
    assert verified.event_id != received.event_id


def test_trace_context_travels_with_the_chain() -> None:
    """So a replay rejoins the original trace instead of appearing as an orphan span."""
    received = an_event().model_copy(update={"trace_context": {"traceparent": "00-abc-def-01"}})

    verified = received.caused("sarana.incident.verified", {}, producer="agent-svc")

    assert verified.trace_context == {"traceparent": "00-abc-def-01"}


def test_ordering_is_per_correlation_id_only() -> None:
    """Not global. A consumer that assumes otherwise is wrong, so the key says so."""
    event = an_event()

    assert event.partition_key == str(event.correlation_id)


def test_a_replay_is_marked_and_keeps_its_origin() -> None:
    original = an_event()

    replayed = original.as_replay()

    assert replayed.is_replay
    assert replayed.replay_of == original.event_id
    assert replayed.event_id != original.event_id
    assert replayed.correlation_id == original.correlation_id


def test_an_original_is_not_a_replay() -> None:
    assert an_event().is_replay is False


def test_half_a_replay_marking_is_refused() -> None:
    """One field without the other would let a replayed event pass as an original."""
    with pytest.raises(ValidationError, match="set together"):
        EventEnvelope(
            event_type="sarana.incident.report.received",
            producer="incident-svc",
            replay_of=uuid7(),
        )


def test_a_naive_occurred_at_is_refused() -> None:
    from datetime import datetime

    with pytest.raises(ValidationError):
        EventEnvelope(
            event_type="sarana.incident.report.received",
            producer="incident-svc",
            occurred_at=datetime(2025, 11, 28, 4, 30),  # noqa: DTZ001 - the point of the test
        )


def test_an_unknown_field_is_refused() -> None:
    """A typo at the publisher should fail there, not silently vanish."""
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_type="sarana.incident.report.received",
            producer="incident-svc",
            correlaton_id=uuid7(),  # type: ignore[call-arg]  # deliberate typo
        )
