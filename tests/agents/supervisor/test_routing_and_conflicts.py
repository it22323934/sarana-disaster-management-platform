"""The routing table, the sequencing constraints, and conflicts that escalate.

The dangerous failure in this agent is not a wrong answer — it is **a route that fires
early**. An incident reaching triage before intake verified it is a crew dispatched on an
unverified report, and nothing downstream would catch it.

So the sequencing tests here matter more than the routing ones, and the conflict tests matter
most of all: the supervisor never auto-resolves a conflict touching life safety or money, and
there is no branch in `escalate` that applies a recommendation.
"""

from __future__ import annotations

from agent_svc.agents.supervisor import conflicts, routes
from agent_svc.agents.supervisor import graph as supervisor
from agent_svc.agents.supervisor.routes import (
    FACT_CAP_VALID,
    FACT_DEDUPLICATED,
    FACT_TRILINGUAL,
    FACT_VERIFIED,
)
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state
from sarana_shared.events import catalogue
from tests.agents.supervisor.conftest import (
    GOOD_PROPOSAL,
    NOW,
    BrokenCall,
    FakeApprovals,
    RecordingCall,
    RecordingStarter,
)

VERIFIED = {FACT_VERIFIED, FACT_DEDUPLICATED}


# ---------------------------------------------------------------------------------------
# Routing is a table
# ---------------------------------------------------------------------------------------


def test_a_declared_hazard_starts_the_forecast_agent() -> None:
    routing = routes.route(catalogue.HAZARD_EVENT_DECLARED, {"hazard_type": "CYCLONE"})

    assert [trigger.agent for trigger in routing.fired] == ["forecast"]


def test_a_report_starts_intake() -> None:
    routing = routes.route(catalogue.INCIDENT_REPORT_RECEIVED, {"channel": "SMS"})

    assert [trigger.agent for trigger in routing.fired] == ["intake"]


def test_a_forecast_below_the_alerting_threshold_starts_nothing() -> None:
    """Class 1 is rain approaching a division's own threshold. A public alert there is the
    one people learn to ignore before the one that mattered."""
    routing = routes.route(
        catalogue.FORECAST_IMPACT_GENERATED,
        {"by_impact_class": {"1": 40}},
        known_facts={FACT_CAP_VALID, FACT_TRILINGUAL},
    )

    assert routing.fired == []
    assert routing.skipped


def test_a_forecast_at_the_threshold_starts_the_warning_agent() -> None:
    routing = routes.route(
        catalogue.FORECAST_IMPACT_GENERATED,
        {"by_impact_class": {"1": 40, "3": 6}},
        known_facts={FACT_CAP_VALID, FACT_TRILINGUAL},
    )

    assert [trigger.agent for trigger in routing.fired] == ["warning"]


def test_an_unrouted_event_starts_nothing_and_is_not_an_error() -> None:
    """Most events on the bus are not for the supervisor."""
    routing = routes.route("sarana.alert.delivery.confirmed", {})

    assert not routing.fired
    assert not routing.has_violation


def test_a_predicate_that_raises_does_not_become_a_poison_pill() -> None:
    """An event missing a field a predicate reads is a contract problem between two
    services. Letting it stop the consumer would block every well-formed event behind it."""
    exploding = routes.Trigger(agent="warning", when=lambda payload: payload["missing"] > 1)

    routing = routes.route("x", {}, table={"x": (exploding,)})

    assert not routing.fired
    assert not routing.has_violation


def test_every_routed_agent_exists() -> None:
    """An agent named in the table but absent from the registry is a route that fails at
    the moment it is needed."""
    from agent_svc.agents import SPECS

    known = {spec.name for spec in SPECS}

    assert set(routes.agents_routed()) <= known


def test_the_subscribed_types_are_stable_across_restarts() -> None:
    """A consumer group whose declared types shuffle between deployments is one whose
    stream reads move around."""
    assert list(routes.subscribed_event_types()) == sorted(routes.subscribed_event_types())


# ---------------------------------------------------------------------------------------
# Sequencing — the constraint that matters
# ---------------------------------------------------------------------------------------


def test_triage_is_refused_before_intake_has_verified_the_incident() -> None:
    """**The constraint that matters most.** A crew sent on an unverified, undeduplicated
    report is a crew sent to an address that may not exist while a real one waits."""
    routing = routes.route(catalogue.INCIDENT_VERIFIED, {}, known_facts=set())

    assert routing.fired == []
    assert routing.has_violation
    assert routing.refused[0][0].agent == "triage"
    assert set(routing.refused[0][1]) == {FACT_VERIFIED, FACT_DEDUPLICATED}


def test_triage_runs_once_intake_has_finished() -> None:
    routing = routes.route(catalogue.INCIDENT_VERIFIED, {}, known_facts=VERIFIED)

    assert [trigger.agent for trigger in routing.fired] == ["triage"]


def test_a_partial_precondition_still_refuses() -> None:
    """Verified but not deduplicated is a report that may be somebody else's emergency."""
    routing = routes.route(catalogue.INCIDENT_VERIFIED, {}, known_facts={FACT_VERIFIED})

    assert routing.has_violation
    assert routing.refused[0][1] == (FACT_DEDUPLICATED,)


def test_an_alert_cannot_dispatch_before_cap_and_trilingual_checks_pass() -> None:
    routing = routes.route(
        catalogue.FORECAST_IMPACT_GENERATED,
        {"by_impact_class": {"4": 3}},
        known_facts={FACT_CAP_VALID},
    )

    assert routing.has_violation
    assert routing.refused[0][1] == (FACT_TRILINGUAL,)


def test_a_refusal_is_distinguishable_from_a_skip() -> None:
    """ "This event was not for that agent" and "that agent should have run and could not"
    are different situations, and only one of them needs a person."""
    skipped = routes.route(
        catalogue.FORECAST_IMPACT_GENERATED,
        {"by_impact_class": {"1": 5}},
        known_facts={FACT_CAP_VALID, FACT_TRILINGUAL},
    )
    refused = routes.route(
        catalogue.FORECAST_IMPACT_GENERATED, {"by_impact_class": {"4": 5}}, known_facts=set()
    )

    assert skipped.skipped and not skipped.has_violation
    assert refused.has_violation and not refused.skipped


async def test_a_sequencing_violation_routes_to_a_person_and_starts_nothing() -> None:
    """End to end: it never proceeds "just this once"."""
    approvals = FakeApprovals(facts={"inc-1": set()})
    starter = RecordingStarter()
    graph = supervisor.build(
        memory_checkpointer(), approvals=approvals, start_agent=starter, now=NOW
    )

    state = initial_state(
        agent="supervisor", subject_type="event", subject_id="inc-1", correlation_id="c-1"
    )
    state["output"] = {
        "event_type": catalogue.INCIDENT_VERIFIED,
        "subject_id": "inc-1",
        "payload": {},
    }
    values = await graph.ainvoke(state, config_for("supervisor:event:inc-1"))

    assert values["__interrupt__"]
    assert starter.started == []


# ---------------------------------------------------------------------------------------
# Conflicts escalate, never resolve
# ---------------------------------------------------------------------------------------


def a_conflict(kind: str = "duplicate_link_disputed") -> conflicts.Conflict:
    return conflicts.Conflict(
        kind=kind,
        subject_type="incident",
        subject_id="inc-1",
        position_a=conflicts.Position(
            source="intake",
            claim="these two reports are the same collapsed house",
            confidence=0.82,
            evidence={"cosine": 0.86},
        ),
        position_b=conflicts.Position(
            source="responder",
            claim="two separate buildings on the same street",
            confidence=0.95,
            evidence={"observed": "on scene"},
        ),
    )


async def test_a_conflict_is_escalated_and_nothing_is_applied() -> None:
    escalation = await conflicts.escalate(a_conflict(), call=RecordingCall(GOOD_PROPOSAL))

    assert escalation.paused
    payload = escalation.as_interrupt_payload()
    assert set(payload["options"]) == {"A", "B"}
    assert payload["proposal"]["is_a_proposal"] is True


async def test_a_proposal_that_cannot_state_the_counter_case_is_suppressed() -> None:
    """A model that cannot say why the other position might be right has picked a side
    rather than weighed two, and a human reading a confident one-sided proposal adopts it."""
    one_sided = (
        '{"recommended": "A", "rationale": "The embeddings matched.", '
        '"why_the_other_might_be_right": "", "confidence": 0.9}'
    )

    result = await conflicts.adjudicate(a_conflict(), call=RecordingCall(one_sided))

    assert result is conflicts.NO_PROPOSAL


async def test_an_unavailable_model_still_escalates_with_both_positions() -> None:
    escalation = await conflicts.escalate(a_conflict(), call=BrokenCall())

    assert escalation.paused
    assert escalation.proposal.method == "TEMPLATE"
    assert escalation.as_interrupt_payload()["options"]["B"]["claim"]


async def test_no_model_at_all_still_escalates() -> None:
    escalation = await conflicts.escalate(a_conflict(), call=None)

    assert escalation.proposal is conflicts.NO_PROPOSAL
    assert escalation.paused


def test_every_conflict_touches_life_safety_or_money() -> None:
    """Including one nobody anticipated. The default is to ask."""
    assert a_conflict().touches_life_safety_or_money
    assert a_conflict(kind="something_new").touches_life_safety_or_money


def test_an_unknown_kind_is_marked_as_unanticipated() -> None:
    """It still escalates; the distinction is only so a log can say "something new"."""
    assert a_conflict().is_a_known_kind
    assert not a_conflict(kind="something_new").is_a_known_kind


async def test_the_prompt_shows_both_positions_symmetrically() -> None:
    """A prompt that presented one position first and in more detail would be asking a
    leading question."""
    call = RecordingCall(GOOD_PROPOSAL)

    await conflicts.adjudicate(a_conflict(), call=call)
    prompt = call.prompts[0]

    assert "Position A" in prompt
    assert "Position B" in prompt
    assert "not deciding" in prompt


def test_the_escalation_payload_does_not_preselect_the_recommendation() -> None:
    """A screen that pre-selects the proposal converts a decision into a confirmation."""
    escalation = conflicts.Escalation(conflict=a_conflict(), proposal=conflicts.NO_PROPOSAL)
    payload = escalation.as_interrupt_payload()

    assert "selected" not in payload
    assert payload["subject_paused"] is True


async def test_a_conflict_pauses_the_subject_through_the_graph() -> None:
    approvals = FakeApprovals(facts={"inc-1": VERIFIED})
    starter = RecordingStarter()
    graph = supervisor.build(
        memory_checkpointer(), approvals=approvals, start_agent=starter, now=NOW
    )

    state = initial_state(
        agent="supervisor", subject_type="event", subject_id="inc-1", correlation_id="c-1"
    )
    state["output"] = {
        "event_type": catalogue.INCIDENT_VERIFIED,
        "subject_id": "inc-1",
        "payload": {},
        "conflict": a_conflict().as_dict(),
    }
    values = await graph.ainvoke(state, config_for("supervisor:event:conflict-1"))

    assert values["__interrupt__"]
    assert starter.started == []


# ---------------------------------------------------------------------------------------
# Rewind
# ---------------------------------------------------------------------------------------


def test_a_thread_that_released_money_cannot_be_rewound() -> None:
    """Build file 18: you cannot rewind released money; you issue a compensating entry."""
    allowed, reason = supervisor.can_rewind({"disbursement_released"})

    assert not allowed
    assert "compensating entry" in reason


def test_a_thread_that_released_a_dispatch_cannot_be_rewound() -> None:
    """A crew that has been sent has been sent."""
    allowed, _ = supervisor.can_rewind({"dispatch_released"})

    assert not allowed


def test_an_uncommitted_thread_can_be_rewound() -> None:
    """The capability has to exist, or a stuck run cannot be recovered."""
    allowed, reason = supervisor.can_rewind({"intake_verified"})

    assert allowed
    assert reason == ""
