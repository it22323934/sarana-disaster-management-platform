"""The event envelope, the correlation chain, and the in-memory bus."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import BaseModel, ValidationError

from sarana_shared.events.bus import InMemoryEventBus, Subscription, matches
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.registry import (
    UnknownEventType,
    export_json_schemas,
    parse_payload,
    register,
)

REPORT_RECEIVED = "sarana.incident.report.received"


def an_event(event_type: str = REPORT_RECEIVED, **kwargs: object) -> EventEnvelope:
    return EventEnvelope(
        type=event_type,
        source="incident-svc",
        payload={"channel": "sms"},
        **kwargs,  # type: ignore[arg-type]  # test helper passthrough
    )


def test_event_type_shape_is_enforced() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(type="IncidentReportReceived", source="incident-svc")


def test_domain_is_read_from_the_type() -> None:
    assert an_event().domain == "incident"


def test_a_caused_event_keeps_the_chain_intact() -> None:
    """The chain from raw citizen report to disbursement is never broken."""
    received = an_event()

    verified = received.caused(
        "sarana.incident.report.verified", {"confidence": 0.91}, source="agent-svc"
    )

    assert verified.correlation_id == received.correlation_id
    assert verified.causation_id == received.event_id
    assert verified.event_id != received.event_id


@pytest.mark.parametrize(
    ("event_type", "patterns", "expected"),
    [
        (REPORT_RECEIVED, (REPORT_RECEIVED,), True),
        (REPORT_RECEIVED, ("sarana.incident.*",), True),
        (REPORT_RECEIVED, ("sarana.ledger.*",), False),
        (REPORT_RECEIVED, ("sarana.ledger.*", "sarana.incident.report.*"), True),
    ],
)
def test_subscription_matching(event_type: str, patterns: tuple[str, ...], expected: bool) -> None:
    assert matches(event_type, patterns) is expected


async def test_the_bus_delivers_to_matching_subscribers_only() -> None:
    bus = InMemoryEventBus()
    incident_seen: list[EventEnvelope] = []
    ledger_seen: list[EventEnvelope] = []

    await bus.subscribe(
        Subscription(group="a", consumer="1", event_types=("sarana.incident.*",)),
        lambda event: _collect(incident_seen, event),
    )
    await bus.subscribe(
        Subscription(group="b", consumer="1", event_types=("sarana.ledger.*",)),
        lambda event: _collect(ledger_seen, event),
    )

    await bus.publish(an_event())

    assert len(incident_seen) == 1
    assert ledger_seen == []


async def test_publishing_is_idempotent_on_event_id() -> None:
    """Delivery is at-least-once, so a redelivered event must not double-append."""
    bus = InMemoryEventBus()
    event = an_event()

    await bus.publish(event)
    await bus.publish(event)

    assert len(bus.published) == 1


async def test_replay_is_bounded_by_the_time_window() -> None:
    """The window is explicit rather than clock-derived.

    Comparing against `utc_now()` taken microseconds later would test the host clock's
    resolution, not the replay bound - and would pass or fail depending on the machine.
    """
    from sarana_shared.domain.time import utc_now

    now = utc_now()
    bus = InMemoryEventBus()
    await bus.publish(an_event(occurred_at=now - timedelta(hours=2)))
    await bus.publish(an_event(occurred_at=now))

    since = now - timedelta(hours=1)
    replayed = [event async for event in bus.replay(("sarana.incident.*",), since)]

    assert len(replayed) == 1
    assert replayed[0].occurred_at == now


def test_registry_validates_a_payload_against_its_model() -> None:
    @register("sarana.alerting.alert.dispatched", version=1)
    class AlertDispatched(BaseModel):
        alert_id: str
        channel_count: int

    envelope = EventEnvelope(
        type="sarana.alerting.alert.dispatched",
        source="alerting-svc",
        payload={"alert_id": "018f", "channel_count": 3},
    )

    parsed = parse_payload(envelope)

    assert isinstance(parsed, AlertDispatched)
    assert parsed.channel_count == 3


def test_an_unregistered_type_is_named_in_the_error() -> None:
    with pytest.raises(UnknownEventType, match=r"sarana\.incident\.report\.received"):
        parse_payload(an_event())


def test_the_schema_catalogue_includes_the_envelope() -> None:
    catalogue = export_json_schemas()

    assert "envelope" in catalogue
    assert "events" in catalogue


async def _collect(sink: list[EventEnvelope], event: EventEnvelope) -> None:
    sink.append(event)
