"""Events starting agent runs.

Most SARANA runs begin here, not from a click, so the failure modes are the ones that
matter on a bad night:

  *A redelivered event starting a second run.* Two officers get the same approval and one
  of them acts on stale information.

  *An event arriving while somebody is deciding.* LangGraph takes fresh input on an
  interrupted thread as a new update from START, so a duplicate event re-enters the graph
  at the top and rebuilds the approval an officer is halfway through answering.

  *A message nothing can route being redelivered forever.* One poison pill stops every
  well-formed event queued behind it, and the outage looks nothing like its cause.

These run against the registry and a fake envelope rather than a bus, because what is
under test is the routing decision, not Redis.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from agent_svc.agents.noop import SPEC as NOOP_SPEC
from agent_svc.consumers import (
    ENVELOPE_SUBJECT,
    TRIGGERS,
    AgentTrigger,
    AgentTriggerWorker,
    enabled_triggers,
    handle,
    subscribed_event_types,
)
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.registry import AgentRegistry
from sarana_shared.events import catalogue
from sarana_shared.events.envelope import EventEnvelope

REPORT_RECEIVED = catalogue.INCIDENT_REPORT_RECEIVED
DISBURSED = catalogue.AID_DISBURSEMENT_RELEASED

NOOP_TRIGGER = AgentTrigger(
    event_type=REPORT_RECEIVED,
    agent="noop",
    subject_from=ENVELOPE_SUBJECT,
    carry=("text",),
)


@pytest.fixture
def registry() -> AgentRegistry:
    """A registry hosting only the reference agent, on an in-process checkpointer."""
    built = AgentRegistry()
    built.register(NOOP_SPEC)
    built.compile_all(memory_checkpointer())
    return built


def event(
    subject: str, payload: dict[str, Any], event_type: str = REPORT_RECEIVED
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        schema_version=1,
        correlation_id=uuid4(),
        producer="core-api",
        subject=subject,
        payload=payload,
    )


async def run(
    registry: AgentRegistry, envelope: EventEnvelope, *, triggers: Any = None
) -> str | None:
    return await handle(envelope, registry=registry, triggers=triggers or (NOOP_TRIGGER,))


# --------------------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------------------


async def test_an_event_starts_the_agent_it_names(registry: AgentRegistry) -> None:
    note = await run(registry, event("rep-1", {"text": "there is a FLOOD here"}))

    assert note == "noop:completed"

    snapshot = await registry.graph("noop").aget_state(config_for("noop:report:rep-1"))
    assert snapshot.values["output"]["category"] == "flood"


async def test_the_run_lands_on_the_thread_the_subject_names(registry: AgentRegistry) -> None:
    """So the ops console can link straight to it, and a resume needs no lookup table."""
    await run(registry, event("rep-2", {"text": "flood"}))

    snapshot = await registry.graph("noop").aget_state(config_for("noop:report:rep-2"))
    assert snapshot.values["subject_id"] == "rep-2"


async def test_the_causation_chain_survives_the_hop(registry: AgentRegistry) -> None:
    """The thread from a citizen's SMS to whatever the state eventually did about it.

    Broken here, and an auditor asking "why did this dispatch happen?" gets a run with no
    parent.
    """
    envelope = event("rep-3", {"text": "flood"})

    await run(registry, envelope)

    snapshot = await registry.graph("noop").aget_state(config_for("noop:report:rep-3"))
    assert snapshot.values["causation_id"] == str(envelope.event_id)
    assert snapshot.values["correlation_id"] == str(envelope.correlation_id)


async def test_only_the_named_fields_reach_the_agent(registry: AgentRegistry) -> None:
    """A checkpoint outlives the run and goes to a trace exporter that leaves the country.

    Copying an event payload wholesale into agent state is how a phone number ends up in
    one (ADR-011), so a field not named in `carry` does not travel.
    """
    await run(
        registry,
        event("rep-4", {"text": "flood", "reporter_phone": "+94771234567", "nic": "199012345678"}),
    )

    snapshot = await registry.graph("noop").aget_state(config_for("noop:report:rep-4"))
    serialised = str(snapshot.values)
    assert "+94771234567" not in serialised
    assert "199012345678" not in serialised


# --------------------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------------------


async def test_a_redelivered_event_rejoins_rather_than_forking(registry: AgentRegistry) -> None:
    """The one that puts two officers on the same decision if it fails."""
    envelope = event("rep-5", {"text": "please help us"})

    first = await run(registry, envelope)
    second = await run(registry, envelope)

    assert first == "noop:interrupted"
    assert second == "noop:interrupted"

    graph = registry.graph("noop")
    snapshot = await graph.aget_state(config_for("noop:report:rep-5"))
    assert len(snapshot.interrupts) == 1, "a redelivery forked a second approval"


async def test_a_second_event_does_not_disturb_a_pending_approval(
    registry: AgentRegistry,
) -> None:
    """An officer halfway through answering must not have the question rebuilt under them.

    LangGraph treats fresh input on an interrupted thread as a new update from START: the
    graph re-enters at the top and every pre-interrupt node runs again. `start_run` rejoins
    instead, which is the whole reason it exists.
    """
    graph = registry.graph("noop")
    await run(registry, event("rep-6", {"text": "unclear"}))
    before = await graph.aget_state(config_for("noop:report:rep-6"))

    # A different event id — so no idempotency claim would stop it — about the same subject.
    await run(registry, event("rep-6", {"text": "still unclear"}))
    after = await graph.aget_state(config_for("noop:report:rep-6"))

    assert after.values["notes"] == before.values["notes"], "the run was restarted"
    assert after.interrupts[0].value == before.interrupts[0].value


async def test_a_finished_run_can_be_started_again(registry: AgentRegistry) -> None:
    """Rejoining applies to work in flight, not work that is over.

    Otherwise a subject could never be reprocessed after a fix, and the only way to re-run
    an agent would be to invent a new subject id.
    """
    await run(registry, event("rep-7", {"text": "flood"}))
    note = await run(registry, event("rep-7", {"text": "landslide"}))

    assert note == "noop:completed"
    snapshot = await registry.graph("noop").aget_state(config_for("noop:report:rep-7"))
    assert snapshot.values["output"]["category"] == "landslide"


# --------------------------------------------------------------------------------------
# Refusals that acknowledge rather than raise
# --------------------------------------------------------------------------------------


async def test_an_event_with_no_subject_is_not_a_poison_pill(registry: AgentRegistry) -> None:
    """It will never succeed, so redelivering it forever blocks everything behind it."""
    envelope = event("", {"text": "flood"})

    note = await run(registry, envelope)

    assert note == "no_run_started"


async def test_a_trigger_naming_an_absent_agent_is_not_a_poison_pill(
    registry: AgentRegistry,
) -> None:
    """A deployment mistake, not a message problem: redelivery will not find the agent."""
    trigger = AgentTrigger(
        event_type=REPORT_RECEIVED, agent="forecast", subject_from=ENVELOPE_SUBJECT, carry=()
    )

    note = await run(registry, event("rep-8", {"text": "flood"}), triggers=(trigger,))

    assert note == "no_run_started"


async def test_an_unroutable_event_is_acknowledged(registry: AgentRegistry) -> None:
    """Being handed a type nothing handles means the subscription and the table have
    fallen out of step. Worth saying loudly; not worth redelivering."""
    note = await run(registry, event("x", {}, event_type=catalogue.AID_GRIEVANCE_RAISED))

    assert note == "unhandled_event_type"


async def test_a_graph_failure_propagates(registry: AgentRegistry) -> None:
    """The one case that must come back.

    A transient failure that got acknowledged is a citizen report nobody ever looks at
    again, so the exception is not caught: the bus redelivers the unacknowledged event.
    """

    class Broken:
        def names(self) -> list[str]:
            return ["noop"]

        def spec(self, _name: str) -> Any:
            return NOOP_SPEC

        def graph(self, _name: str) -> Any:
            raise RuntimeError("the checkpointer is unreachable")

    with pytest.raises(RuntimeError):
        await handle(event("rep-9", {"text": "flood"}), registry=Broken(), triggers=(NOOP_TRIGGER,))


# --------------------------------------------------------------------------------------
# Subject extraction
# --------------------------------------------------------------------------------------


def test_a_subject_can_come_from_inside_the_payload() -> None:
    """Not every event's envelope subject is what the agent works on: a disbursement event
    is subject to the disbursement, and the anomaly agent works on the household."""
    trigger = AgentTrigger(event_type=DISBURSED, agent="a", subject_from="household.id", carry=())

    envelope = event("disb-1", {"household": {"id": "hh-77"}}, event_type=DISBURSED)

    assert trigger.subject_id(envelope) == "hh-77"


def test_a_missing_payload_path_reports_nothing_rather_than_raising() -> None:
    trigger = AgentTrigger(event_type=DISBURSED, agent="a", subject_from="household.id", carry=())

    assert trigger.subject_id(event("d", {"household": {}}, event_type=DISBURSED)) is None
    assert trigger.subject_id(event("d", {}, event_type=DISBURSED)) is None


# --------------------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------------------


def test_every_trigger_names_an_event_the_platform_publishes() -> None:
    """A row pointed at a type nothing emits is a wire that was never connected, and it
    fails silently — the agent simply never runs."""
    for trigger in TRIGGERS:
        assert trigger.event_type in catalogue.ALL_EVENT_TYPES, trigger.event_type


def test_the_reference_agent_does_not_run_on_real_citizen_reports() -> None:
    """`noop` classifies with three keywords and asks a person about everything else.

    Pointed at live reports it would fill the approval inbox with questions no officer can
    usefully answer, and an inbox people learn to ignore is worse than no inbox. File 15
    replaces this row with the intake agent.
    """
    assert not any(trigger.agent == "noop" and trigger.enabled for trigger in TRIGGERS)


def test_the_subscribed_types_are_stable_across_restarts() -> None:
    """A consumer group whose declared types shuffle between deployments is one whose
    stream reads move around."""
    shuffled = (
        AgentTrigger(event_type="b", agent="x", subject_from=ENVELOPE_SUBJECT, carry=()),
        AgentTrigger(event_type="a", agent="y", subject_from=ENVELOPE_SUBJECT, carry=()),
        AgentTrigger(event_type="b", agent="z", subject_from=ENVELOPE_SUBJECT, carry=()),
    )

    assert subscribed_event_types(shuffled) == ("a", "b")


def test_a_disabled_row_is_not_subscribed_to() -> None:
    off = (AgentTrigger("a", "x", ENVELOPE_SUBJECT, (), enabled=False),)

    assert enabled_triggers(off) == ()
    assert subscribed_event_types(off) == ()


def test_a_worker_with_nothing_enabled_does_not_subscribe(registry: AgentRegistry) -> None:
    """It would subscribe to everything on some transports and to nothing on others.

    Saying so at boot beats either.
    """
    worker = AgentTriggerWorker(
        None,  # type: ignore[arg-type]
        bus=None,  # type: ignore[arg-type]
        registry=registry,
        triggers=(AgentTrigger("a", "noop", ENVELOPE_SUBJECT, (), enabled=False),),
    )

    assert worker.subscribes_to == ()
    worker.start()  # must not raise, and must not create a task with no bus


def test_starting_an_agent_is_never_replayable(registry: AgentRegistry) -> None:
    """Agents draft alerts, propose dispatches and flag disbursements.

    Replaying a week of incident events into this consumer would re-run every one of
    those, so the subscription declares itself side-effecting and the bus refuses to hand
    it a replay at all. Asserted on the source because the alternative is discovering it
    during a replay.
    """
    from pathlib import Path

    source = Path(AgentTriggerWorker.__module__.replace(".", "/"))
    text = (Path("services/agent-svc/src") / source.with_suffix(".py")).read_text(encoding="utf-8")

    assert "side_effect_free=False" in text
