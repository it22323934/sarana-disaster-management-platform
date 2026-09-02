"""The graph end to end, the degraded path, and what a rejection is worth.

The property this file exists for beyond the gate: **a total model outage is close to a
non-event for this agent**. Build file 16 asks for that explicitly, and it is true here
because scoring, ranking, resource checking and routing never touch a model at all. Only the
rationale does, and it is downstream of every decision.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langgraph.types import Command

from agent_svc.agents.triage import graph as triage
from agent_svc.agents.triage import plan as plan_rules
from agent_svc.agents.triage import rejections
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state
from sarana_shared.domain.localised import REQUIRED_LOCALES
from tests.agents.triage.conftest import (
    DELTOTA,
    NOW,
    PERADENIYA,
    BrokenCall,
    FakeIncidents,
    FakePlanStore,
    FakeResponders,
    RecordingCall,
    incident,
    responder,
)


def build_graph(store: FakePlanStore, *, queue=None, crews=None, **kwargs):
    return triage.build(
        memory_checkpointer(),
        incidents=FakeIncidents(queue=queue if queue is not None else [incident("i1")]),
        responders=FakeResponders(crews=crews if crews is not None else [responder("r1")]),
        store=store,
        now=NOW,
        **kwargs,
    )


async def run(graph, *, subject: str = "plan-1"):
    state = initial_state(
        agent="triage",
        subject_type="dispatch_plan",
        subject_id=subject,
        correlation_id="test-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    config = config_for(f"triage:dispatch_plan:{subject}")
    return await graph.ainvoke(state, config), config


def approve(subject: str, **extra) -> Command:
    return Command(
        resume={
            "subject_id": subject,
            "decided_by": "dispatcher-1",
            "decided_at": datetime.now(UTC).isoformat(),
            "approved": True,
            **extra,
        }
    )


def reject(subject: str, **extra) -> Command:
    return Command(
        resume={
            "subject_id": subject,
            "decided_by": "dispatcher-1",
            "decided_at": datetime.now(UTC).isoformat(),
            "approved": False,
            **extra,
        }
    )


# ---------------------------------------------------------------------------------------
# The approval screen's contract
# ---------------------------------------------------------------------------------------


async def test_the_interrupt_payload_carries_everything_a_dispatcher_needs(
    store: FakePlanStore,
) -> None:
    """Build file 16 calls the payload the approval screen's contract.

    A gate where the person cannot see why is a rubber stamp, not a control.
    """
    graph = build_graph(store)

    values, _ = await run(graph)
    payload = values["__interrupt__"][0].value["detail"]

    for field in (
        "plan_id",
        "incidents",
        "responders",
        "route_summary",
        "unservable",
        "factors",
        "estimated_duration_min",
    ):
        assert field in payload, f"the approval screen needs {field}"


async def test_the_payload_shows_the_factor_breakdown_for_every_incident(
    store: FakePlanStore,
) -> None:
    """A dispatcher who disagrees with a ranking needs to point at the term they disagree
    with. That is what makes it contestable rather than something to be over-trusted."""
    graph = build_graph(store, queue=[incident("i1"), incident("i2", at=PERADENIYA)])

    values, _ = await run(graph)
    factors = values["__interrupt__"][0].value["detail"]["factors"]

    assert len(factors) == 2
    assert set(factors[0]["factors"]["weights"]) == {
        "immediate_danger",
        "people_at_risk",
        "vulnerability",
        "incident_type",
        "age",
        "corroboration",
    }


async def test_an_unservable_incident_reaches_the_approval_screen(
    store: FakePlanStore,
) -> None:
    """The one a dispatcher escalates. A plan that showed only what it proposed would be
    approved while somebody nobody saw was left unreached."""
    graph = build_graph(
        store,
        queue=[incident("placed"), incident("unplaced", at=None)],
        crews=[responder("r1")],
    )

    values, _ = await run(graph)
    unservable = values["__interrupt__"][0].value["detail"]["unservable"]

    assert [item["incident_id"] for item in unservable] == ["unplaced"]
    assert unservable[0]["detail"]


# ---------------------------------------------------------------------------------------
# The degraded path
# ---------------------------------------------------------------------------------------


async def test_the_ranking_is_identical_with_and_without_a_model(
    store: FakePlanStore,
) -> None:
    """The property build file 16 asks for: a total model outage is close to a non-event.

    Scoring, ranking and routing never touch a model, so the only thing that can differ is
    the prose.
    """
    queue = [
        incident("a", people=6, minutes_ago=30),
        incident("b", people=1, minutes_ago=90, at=PERADENIYA),
        incident("c", incident_type="MEDICAL", danger=True, at=DELTOTA),
    ]

    without, _ = await run(build_graph(FakePlanStore(), queue=queue), subject="no-model")
    with_model, _ = await run(
        build_graph(
            store,
            queue=queue,
            call=RecordingCall('{"si": "සිංහල", "ta": "தமிழ்", "en": "English"}'),
        ),
        subject="with-model",
    )

    assert [item["incident_id"] for item in without["scores"]] == [
        item["incident_id"] for item in with_model["scores"]
    ]
    assert without["plan"]["route_summary"] == with_model["plan"]["route_summary"]


async def test_a_broken_model_falls_back_to_the_template_rationale(
    store: FakePlanStore,
) -> None:
    graph = build_graph(store, call=BrokenCall())

    values, _ = await run(graph)

    assert values["plan"]["rationale_method"] == "TEMPLATE"
    assert all(values["plan"]["rationale"][locale.value] for locale in REQUIRED_LOCALES)


async def test_a_rationale_missing_a_language_is_discarded_whole(
    store: FakePlanStore,
) -> None:
    """Partial output is the one thing this platform never renders. A rationale missing
    Tamil is replaced by the template, which has all three."""
    graph = build_graph(store, call=RecordingCall('{"si": "සිංහල", "en": "English"}'))

    values, _ = await run(graph)

    assert values["plan"]["rationale_method"] == "TEMPLATE"


async def test_a_complete_model_rationale_is_used(store: FakePlanStore) -> None:
    graph = build_graph(
        store, call=RecordingCall('{"si": "සිංහල වාක්‍යය", "ta": "தமிழ் வாக்கியம்", "en": "A sentence"}')
    )

    values, _ = await run(graph)

    assert values["plan"]["rationale_method"] == "LLM"
    assert values["plan"]["rationale"]["en"] == "A sentence"


def test_the_template_rationale_is_trilingual() -> None:
    from agent_svc.agents.triage.scoring import TriageFactors, WeightedSumModel

    scored = [WeightedSumModel().score(TriageFactors("i1", "FLOOD", immediate_danger=True))]
    rendered = plan_rules.template_rationale(scored, {"i1": incident("i1")})

    assert all(rendered[locale.value].strip() for locale in REQUIRED_LOCALES)


def test_the_rationale_names_the_heaviest_factor_rather_than_a_fixed_one() -> None:
    """If the heaviest term changes, the prose changes with it - so the sentence and the
    numbers cannot drift apart."""
    from agent_svc.agents.triage.scoring import TriageFactors, WeightedSumModel

    danger = WeightedSumModel().score(TriageFactors("i1", "FLOOD", immediate_danger=True))
    old = WeightedSumModel().score(TriageFactors("i2", "FLOOD", minutes_since_report=600))

    assert plan_rules.top_driver(danger) == "immediate_danger"
    assert plan_rules.top_driver(old) == "age"


# ---------------------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------------------


async def test_a_rejection_records_a_taxonomy_reason_and_an_observation(
    store: FakePlanStore,
) -> None:
    """The highest-value data the platform produces. An agent that logged "plan rejected"
    and moved on would discard the only supervision signal it will ever get."""
    graph = build_graph(store)
    subject = "plan-reject"

    _, config = await run(graph, subject=subject)
    resumed = await graph.ainvoke(
        reject(subject, reason="already_handled", note="the family walked out an hour ago"),
        config,
    )

    assert store.rejected[0]["reason"] == "already_handled"
    assert resumed["output"]["released"] is False
    assert any(
        observation["observation"] == "dispatch_plan_rejected"
        for observation in resumed["observations"]
    )


def test_an_unrecognised_reason_is_preserved_rather_than_refused() -> None:
    """The dispatcher has already decided by the time this runs. Refusing to record their
    reason to protect a vocabulary would lose the signal."""
    recorded = rejections.record(
        {"reason": "the boat sank", "decided_by": "dispatcher-1"}, plan_id="plan-1"
    )

    assert recorded.reason == "other"
    assert "the boat sank" in (recorded.note or "")


def test_a_missing_reason_is_recorded_as_such() -> None:
    """So the distribution shows how often the console let somebody through without one."""
    recorded = rejections.record({"decided_by": "dispatcher-1"}, plan_id="plan-1")

    assert recorded.reason == "other"
    assert "no reason" in (recorded.note or "")


def test_the_distribution_counts_every_known_reason() -> None:
    """An accept rate says how often the agent is agreed with; this says how it is wrong,
    which is what a change can be aimed at."""
    counts = rejections.distribution(
        [
            rejections.record({"reason": "wrong_priority"}, plan_id="p1"),
            rejections.record({"reason": "wrong_priority"}, plan_id="p2"),
            rejections.record({"reason": "bad_location"}, plan_id="p3"),
        ]
    )

    assert counts["wrong_priority"] == 2
    assert counts["bad_location"] == 1
    assert set(counts) == set(rejections.REASONS)


def test_a_rejection_produces_one_observation_per_incident() -> None:
    """Per incident rather than per plan, because the Learn loop asks "was this incident
    ranked correctly?" and a plan-level record cannot answer it."""
    recorded = rejections.record({"reason": "duplicate"}, plan_id="p1")
    observations = recorded.observations(["i1", "i2"], agent="triage")

    assert [item["subject_id"] for item in observations] == ["i1", "i2"]
    assert all(item["value"] == "duplicate" for item in observations)


# ---------------------------------------------------------------------------------------
# Empty and refusing cases
# ---------------------------------------------------------------------------------------


async def test_an_empty_queue_completes_without_asking_a_dispatcher(
    store: FakePlanStore,
) -> None:
    """Putting an empty plan in front of a dispatcher trains them to approve without
    looking, which is precisely how a gate stops being one."""
    graph = build_graph(store, queue=[])

    values, _ = await run(graph)

    assert not values.get("__interrupt__")
    assert not store.proposed


async def test_no_available_responders_completes_without_asking(store: FakePlanStore) -> None:
    graph = build_graph(store, crews=[responder("r1", status="EN_ROUTE")])

    values, _ = await run(graph)

    assert not values.get("__interrupt__")
    assert not store.proposed


async def test_an_undispatchable_incident_is_never_ranked_down(store: FakePlanStore) -> None:
    """It stays at full urgency in the queue and comes back as unservable. Ranking it down
    would quietly deprioritise the people the platform serves worst."""
    graph = build_graph(
        store,
        queue=[
            incident("unplaceable", location_confidence=0.05, people=8, danger=True, at=None),
            incident("ordinary", people=1),
        ],
    )

    values, _ = await run(graph)

    # It is still top of the queue on urgency...
    assert values["scores"][0]["incident_id"] == "unplaceable"
    # ...and it is not in a route.
    assert "unplaceable" not in values["plan"]["served"]


async def test_a_graph_with_no_sources_refuses_rather_than_planning_nothing() -> None:
    """An empty queue and an unreachable database produce the same empty plan and mean
    opposite things, and only one of them means everybody has been rescued."""
    graph = triage.build(memory_checkpointer())

    with pytest.raises(RuntimeError, match="incident source"):
        await run(graph, subject="refusing")
