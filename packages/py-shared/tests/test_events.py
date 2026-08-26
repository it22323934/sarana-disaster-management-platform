from uuid import uuid4

import pytest
from pydantic import BaseModel
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from sarana_shared.events.registry import ALL_EVENT_TYPES, EventRegistryError, _Registry


def _make_envelope(event_type: str = "sarana.incident.report.received") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        correlation_id=uuid4(),
        producer="test",
        payload={"hello": "world"},
    )


@pytest.mark.asyncio
async def test_publish_delivers_to_matching_subscriber() -> None:
    bus = InMemoryEventBus()
    received: list[EventEnvelope] = []

    async def handler(envelope: EventEnvelope) -> None:
        received.append(envelope)

    await bus.subscribe(["sarana.incident.report.received"], "test-group", handler)
    envelope = _make_envelope()
    await bus.publish(envelope)

    assert received == [envelope]
    assert bus.published() == [envelope]


@pytest.mark.asyncio
async def test_publish_does_not_deliver_to_non_matching_subscriber() -> None:
    bus = InMemoryEventBus()
    received: list[EventEnvelope] = []

    async def handler(envelope: EventEnvelope) -> None:
        received.append(envelope)

    await bus.subscribe(["sarana.alert.dispatched"], "test-group", handler)
    await bus.publish(_make_envelope("sarana.incident.report.received"))

    assert received == []


@pytest.mark.asyncio
async def test_replay_marks_envelopes_as_replayed() -> None:
    from sarana_shared.domain.time import now_utc

    bus = InMemoryEventBus()
    received: list[EventEnvelope] = []

    async def handler(envelope: EventEnvelope) -> None:
        received.append(envelope)

    # Publish BEFORE subscribing — nothing is delivered live, since publish() fans out
    # only to the subscribers that exist at publish time. This isolates the assertion
    # below to what replay() specifically re-delivers, not what publish() also did.
    original = _make_envelope()
    await bus.publish(original)
    await bus.subscribe(["sarana.incident.report.received"], "replay-group", handler)

    handle = await bus.replay(
        since=now_utc().replace(year=2000),
        until=None,
        event_types=None,
        target_group="replay-group",
    )
    assert await handle.status() == "completed"
    assert len(received) == 1
    assert received[0].is_replay()
    assert received[0].replay_of == original.event_id


def test_registry_round_trip() -> None:
    registry = _Registry()

    @registry.register("sarana.test.thing.happened")
    class ThingHappened(BaseModel):
        value: int

    assert registry.is_registered("sarana.test.thing.happened")
    assert registry.model_for("sarana.test.thing.happened") is ThingHappened
    schema = registry.json_schema_for("sarana.test.thing.happened")
    assert schema["properties"]["value"]["type"] == "integer"


def test_registry_raises_for_unknown_event_type() -> None:
    registry = _Registry()
    with pytest.raises(EventRegistryError):
        registry.model_for("sarana.does.not.exist")


def test_event_catalogue_names_follow_the_convention() -> None:
    """sarana.{domain}.{noun}.{past-tense-verb} — docs/build-prompts/02-conventions.md.
    Not every event has a distinct noun segment (e.g. sarana.alert.drafted), so the real
    invariant is "sarana" + at least a domain + a verb — 3 segments minimum, not 4."""
    assert len(ALL_EVENT_TYPES) == len(set(ALL_EVENT_TYPES))  # no duplicates
    for event_type in ALL_EVENT_TYPES:
        assert event_type.startswith("sarana.")
        assert len(event_type.split(".")) >= 3
