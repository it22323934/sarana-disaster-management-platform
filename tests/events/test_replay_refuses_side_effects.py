"""A replay must never re-send an SMS or re-release money.

Named in the Definition of Done, and the single most important rule in the event system.

Replay exists so a failed agent task can be retried from the last known event. That is
safe for a consumer that recomputes a score or updates a projection. It is not safe for
the consumer that talks to the telco gateway, and it is emphatically not safe for the one
that talks to the bank.

So consumers declare whether they are side-effect free, and the bus refuses to hand a
replayed envelope to one that is not. The refusal is logged, because a silent refusal is
just a different way of losing an event.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import Subscription, refuses_replay
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from sarana_shared.events.replay import (
    MAX_WINDOW,
    ReplayCoordinator,
    ReplayRefused,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROJECTION_GROUP = "resilience-projection"
SMS_GROUP = "telco-gateway"


def a_disbursement() -> EventEnvelope:
    return EventEnvelope(
        event_type="sarana.aid.disbursement.released",
        producer="ledger-svc",
        correlation_id=uuid7(),
        payload={"disbursement_id": str(uuid7()), "amount_lkr_cents": 100_000_000},
    )


def an_alert() -> EventEnvelope:
    return EventEnvelope(
        event_type="sarana.alert.dispatched",
        producer="alerting-svc",
        correlation_id=uuid7(),
        payload={"alert_id": str(uuid7()), "channel": "SMS", "target_count": 4200},
    )


async def test_a_side_effecting_consumer_refuses_a_replay(bus: InMemoryEventBus) -> None:
    """The required case: the SMS consumer refuses and logs."""
    sent: list[EventEnvelope] = []

    async def send_sms(envelope: EventEnvelope) -> None:
        sent.append(envelope)

    await bus.subscribe(
        Subscription(
            group=SMS_GROUP,
            consumer="worker-1",
            event_types=("sarana.alert.*",),
            side_effect_free=False,
        ),
        send_sms,
    )

    original = an_alert()
    await bus.publish(original)
    assert len(sent) == 1, "the first, real dispatch must go out"

    await bus.publish(original.as_replay())

    assert len(sent) == 1, "a replay re-sent an SMS to 4,200 people"
    assert len(bus.refused_replays) == 1


async def test_a_side_effect_free_consumer_reprocesses_a_replay(
    bus: InMemoryEventBus,
) -> None:
    """The other half: replay has to actually work, or it is not worth having."""
    seen: list[EventEnvelope] = []

    async def project(envelope: EventEnvelope) -> None:
        seen.append(envelope)

    await bus.subscribe(
        Subscription(
            group=PROJECTION_GROUP,
            consumer="worker-1",
            event_types=("sarana.alert.*",),
            side_effect_free=True,
        ),
        project,
    )

    original = an_alert()
    await bus.publish(original)
    await bus.publish(original.as_replay())

    assert len(seen) == 2
    assert seen[1].is_replay
    assert seen[1].replay_of == original.event_id


async def test_a_replay_reaches_one_group_and_not_the_other(
    bus: InMemoryEventBus,
) -> None:
    """A replay names its target group. It does not broadcast."""
    projected: list[EventEnvelope] = []
    released: list[EventEnvelope] = []

    await bus.subscribe(
        Subscription(
            group=PROJECTION_GROUP,
            consumer="w",
            event_types=("sarana.aid.*",),
            side_effect_free=True,
        ),
        lambda e: _collect(projected, e),
    )
    await bus.subscribe(
        Subscription(
            group="payment-rail",
            consumer="w",
            event_types=("sarana.aid.*",),
            side_effect_free=False,
        ),
        lambda e: _collect(released, e),
    )

    await bus.publish(a_disbursement())
    assert len(released) == 1

    handle = await bus.replay(
        since=utc_now() - timedelta(hours=1),
        event_types=("sarana.aid.disbursement.released",),
        target_group=PROJECTION_GROUP,
        requested_by="operator-1",
    )

    assert handle.delivered == 1
    assert len(projected) == 2
    assert len(released) == 1, "the replay reached the payment rail"


async def test_the_predicate_is_the_whole_rule() -> None:
    """Stated once, in one function, so there is one place to get it right."""
    original = an_alert()
    replayed = original.as_replay()

    sms = Subscription(
        group=SMS_GROUP, consumer="w", event_types=("sarana.alert.*",), side_effect_free=False
    )
    projection = Subscription(
        group=PROJECTION_GROUP,
        consumer="w",
        event_types=("sarana.alert.*",),
        side_effect_free=True,
    )

    assert refuses_replay(sms, replayed) is True
    assert refuses_replay(sms, original) is False, "a first delivery is never refused"
    assert refuses_replay(projection, replayed) is False


async def _collect(sink: list[EventEnvelope], envelope: EventEnvelope) -> None:
    sink.append(envelope)


async def test_a_replay_must_name_its_event_types(bus: InMemoryEventBus) -> None:
    """There is no replay-everything call.

    On a platform that sends messages and moves money, the blast radius of that mistake
    is not recoverable, so the API does not offer it.
    """
    coordinator = ReplayCoordinator(bus=bus)

    with pytest.raises(ReplayRefused, match="must name its event types"):
        await coordinator.start(
            since=utc_now() - timedelta(hours=1),
            until=None,
            event_types=(),
            target_group=PROJECTION_GROUP,
            requested_by="operator-1",
        )


async def test_a_replay_must_name_one_target_group(bus: InMemoryEventBus) -> None:
    coordinator = ReplayCoordinator(bus=bus)

    with pytest.raises(ReplayRefused, match="exactly one target consumer group"):
        await coordinator.start(
            since=utc_now() - timedelta(hours=1),
            until=None,
            event_types=("sarana.aid.disbursement.released",),
            target_group="",
            requested_by="operator-1",
        )


async def test_an_implausibly_wide_window_is_refused(bus: InMemoryEventBus) -> None:
    """Someone meant days and typed months. One retry costs less than one re-disaster."""
    coordinator = ReplayCoordinator(bus=bus)

    with pytest.raises(ReplayRefused, match="wider than"):
        await coordinator.start(
            since=utc_now() - (MAX_WINDOW * 3),
            until=None,
            event_types=("sarana.aid.disbursement.released",),
            target_group=PROJECTION_GROUP,
            requested_by="operator-1",
        )


async def test_a_wide_window_is_allowed_when_it_is_meant(bus: InMemoryEventBus) -> None:
    """The guard is a speed bump, not a wall. Overriding it is explicit and logged."""
    coordinator = ReplayCoordinator(bus=bus)

    handle = await coordinator.start(
        since=utc_now() - (MAX_WINDOW * 3),
        until=None,
        event_types=("sarana.aid.disbursement.released",),
        target_group=PROJECTION_GROUP,
        requested_by="operator-1",
        allow_wide_window=True,
    )

    assert handle.requested_by == "operator-1"


async def test_a_backwards_window_is_refused(bus: InMemoryEventBus) -> None:
    coordinator = ReplayCoordinator(bus=bus)

    with pytest.raises(ReplayRefused, match="ends before it begins"):
        await coordinator.start(
            since=utc_now(),
            until=utc_now() - timedelta(hours=1),
            event_types=("sarana.aid.disbursement.released",),
            target_group=PROJECTION_GROUP,
            requested_by="operator-1",
        )


async def test_the_coordinator_records_what_each_replay_did(
    bus: InMemoryEventBus,
) -> None:
    """An operator has to be able to answer 'what did that replay actually deliver'."""
    await bus.subscribe(
        Subscription(
            group=PROJECTION_GROUP,
            consumer="w",
            event_types=("sarana.aid.*",),
            side_effect_free=True,
        ),
        lambda e: _collect([], e),
    )
    await bus.publish(a_disbursement())

    coordinator = ReplayCoordinator(bus=bus)
    handle = await coordinator.start(
        since=utc_now() - timedelta(hours=1),
        until=None,
        event_types=("sarana.aid.disbursement.released",),
        target_group=PROJECTION_GROUP,
        requested_by="operator-1",
    )

    assert handle.delivered == 1
    assert coordinator.running is None
    assert coordinator.history[-1].replay_id == handle.replay_id
