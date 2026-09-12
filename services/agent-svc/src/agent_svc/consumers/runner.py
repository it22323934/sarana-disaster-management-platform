"""The worker that turns events into agent runs.

Most SARANA runs start here, not from a click. A report arrives, an event is published, and
some agent picks it up — which is what makes the platform recoverable: no agent calls
another, so an agent that dies mid-run leaves no half-finished conversation, only events
that were either published or not (ADR-003).

Three properties this has to hold, in the order they bite:

**A redelivery must not start a second run.** Two independent reasons it does not. The event
is claimed in `processed_event` in the same transaction as the handler, so a redelivery
finds the claim and stops. And the thread id is derived from the subject, so even a claim
that somehow missed lands on the same thread rather than forking a second approval in front
of a second officer.

**An event arriving while a person is deciding must not disturb them.** `start_run` rejoins
a pending run instead of restarting it. Without that, a duplicate event rebuilds the
approval an officer is halfway through answering.

**A replay must never reach this consumer.** Starting an agent is not a read: agents draft
alerts, propose dispatches and flag disbursements. Replaying a week of incident events into
this worker would re-run every one of those. The subscription declares
`side_effect_free=False` and the bus refuses to hand it a replayed envelope at all.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_svc.adapters.events import CONSUMER_GROUP, handle_idempotently
from agent_svc.consumers.triggers import (
    TRIGGERS,
    AgentTrigger,
    enabled_triggers,
    subscribed_event_types,
)
from agent_svc.runtime.run import start_run
from sarana_shared.events.bus import EventBus, Subscription
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)


async def handle(
    envelope: EventEnvelope,
    *,
    registry: object,
    triggers: tuple[AgentTrigger, ...],
) -> str | None:
    """Start whatever agents this event triggers. Returns a short note for the audit trail.

    Every refusal in here acknowledges the event rather than raising. A malformed or
    unroutable message that is redelivered forever is a poison pill: it blocks every
    well-formed event queued behind it, and the outage that produces looks nothing like its
    cause. Only a genuinely transient failure — the graph itself raising — propagates, and
    that one should come back.
    """
    matched = [trigger for trigger in triggers if trigger.event_type == envelope.event_type]
    if not matched:
        # Subscribed to a type nothing handles. Not fatal, but it means the subscription
        # and the trigger table have fallen out of step, which nobody notices otherwise.
        _log.error("agent_trigger_unhandled_event", event_type=envelope.event_type)
        return "unhandled_event_type"

    started: list[str] = []
    for trigger in matched:
        subject_id = trigger.subject_id(envelope)
        if subject_id is None:
            _log.error(
                "agent_trigger_no_subject",
                event_type=envelope.event_type,
                event_id=str(envelope.event_id),
                subject_from=trigger.subject_from,
                impact="this event started no run and will not be retried",
            )
            continue

        try:
            result = await start_run(
                registry,
                agent=trigger.agent,
                subject_id=subject_id,
                subject_type=trigger.subject_type,
                payload=trigger.input_for(envelope),
                correlation_id=str(envelope.correlation_id),
                causation_id=str(envelope.event_id),
            )
        except KeyError:
            # The trigger names an agent this process does not host. A deployment mistake,
            # not a message problem - redelivering it will not find the agent.
            _log.error(
                "agent_trigger_unknown_agent",
                agent=trigger.agent,
                event_type=envelope.event_type,
                impact="events of this type start no run until the agent is registered",
            )
            continue

        _log.info(
            "agent_triggered_by_event",
            agent=trigger.agent,
            thread_id=result.thread_id,
            event_type=envelope.event_type,
            status=result.status,
            rejoined=result.rejoined,
            awaiting_human=result.waiting_on_a_person,
        )
        started.append(f"{trigger.agent}:{result.status.lower()}")

    return ",".join(started) if started else "no_run_started"


class AgentTriggerWorker:
    """Subscribes to every event in the trigger table and starts the agents it names.

    Failures inside the handler are not swallowed: the bus redelivers an unacknowledged
    event, and the idempotency claim is what stops the redelivery producing a second run.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        bus: EventBus,
        registry: object,
        triggers: tuple[AgentTrigger, ...] = TRIGGERS,
    ) -> None:
        self._factory = session_factory
        self._bus = bus
        self._registry = registry
        self._triggers = enabled_triggers(triggers)
        self._event_types = subscribed_event_types(triggers)
        self._task: asyncio.Task[None] | None = None

    @property
    def subscribes_to(self) -> tuple[str, ...]:
        """What this worker listens for. Read by the boot log and by tests."""
        return self._event_types

    def start(self) -> None:
        """Begin consuming, unless the table has nothing enabled.

        A worker with no types would subscribe to everything on some transports and to
        nothing on others. Saying so at boot is better than either.
        """
        if not self._event_types:
            _log.info(
                "agent_triggers_none_enabled",
                impact="agents start only from the HTTP surface; no event triggers a run",
            )
            return
        self._task = asyncio.create_task(self._loop(), name="agent-triggers")
        _log.info("agent_trigger_worker_started", event_types=list(self._event_types))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        async def on_event(envelope: EventEnvelope) -> None:
            async with self._factory() as session:

                async def run(_session: AsyncSession, event: EventEnvelope) -> str | None:
                    return await handle(event, registry=self._registry, triggers=self._triggers)

                await handle_idempotently(session, envelope, run, group=CONSUMER_GROUP)
                await session.commit()

        await self._bus.subscribe(
            Subscription(
                group=CONSUMER_GROUP,
                consumer=CONSUMER_GROUP,
                event_types=self._event_types,
                # Agents draft alerts, propose dispatches and flag disbursements. Handing
                # this consumer a week of replayed history would re-run all of it, so the
                # bus refuses to deliver a replay here at all.
                side_effect_free=False,
            ),
            on_event,
        )
