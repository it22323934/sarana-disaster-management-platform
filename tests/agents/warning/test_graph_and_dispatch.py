"""The warning graph end to end, and the three layers over the human gate.

`test_an_alert_with_free_text_cannot_reach_dispatched_without_a_signoff` is the one that
matters most in this file. Build file 14 requires it, and it is the property the whole soft
gate exists to hold: template text has been through native review in three languages, and
anything else waits for a named person.

Every test here runs with no network, no database and no model provider, against the fakes
in `conftest.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.types import Command

from agent_svc.agents.warning import graph as warning
from agent_svc.agents.warning.ports import PriorAlert
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.errors import HumanGateMissing
from agent_svc.runtime.state import initial_state
from agent_svc.runtime.tools import REGISTRY as TOOLS
from sarana_shared.domain import cap, sms
from sarana_shared.domain.localised import REQUIRED_LOCALES
from tests.agents.warning.conftest import (
    NIGHT_COLOMBO,
    NOON_COLOMBO,
    FakeDirectory,
    FakeForecasts,
    FakeHistory,
    division,
    household,
)

EVENT = "evt-ditwah"
DIVISION = "LK-21-01-001"


def build_graph(
    *,
    catalogue,
    directory,
    dispatcher,
    divisions=None,
    history=None,
    now=NOON_COLOMBO,
    available=None,
    target_cap=250_000,
):
    """Compile the graph over fakes, with the clock pinned.

    The clock is pinned rather than read: the quiet-hours rule is a claim about what this
    agent does at a particular hour, and a test that could not fix the hour could not test
    it.
    """
    return warning.build(
        memory_checkpointer(),
        forecasts=FakeForecasts(divisions=divisions or [division(DIVISION)]),
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        history=history,
        now=now,
        available_channels=available or ("SMS", "APP", "LORA"),
        target_cap=target_cap,
    )


async def run(graph, *, subject: str, payload: dict | None = None):
    """Start a run and return its final values."""
    thread = f"warning:hazard_event:{subject}"
    state = initial_state(
        agent="warning",
        subject_type="hazard_event",
        subject_id=subject,
        correlation_id="test-correlation",
    )
    state["output"] = payload or {"hazard_event_id": EVENT, "hazard_type": "FLOOD"}
    return await graph.ainvoke(state, config_for(thread)), config_for(thread)


# ---------------------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------------------


async def test_a_major_impact_forecast_produces_a_dispatched_alert(
    catalogue, directory, dispatcher
) -> None:
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert values["status"] == "COMPLETED"
    assert values["output"]["template_code"] == "FLOOD_WARNING"
    assert values["output"]["targeted"] == 10
    assert values["output"]["confirmed"] == 10
    assert dispatcher.orders


async def test_every_dispatched_alert_validates_against_cap_and_carries_three_languages(
    catalogue, directory, dispatcher
) -> None:
    """Required by build file 14.

    The CAP document is built and validated inside the graph, before anything is sent - so
    a schema-invalid alert never reaches a broadcaster, and a missing Tamil body never
    reaches a district.
    """
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))
    document = values["validation"]["cap_xml"]

    assert document is not None
    assert cap.parse_problems(document) == []

    order = dispatcher.orders[0]
    for locale in REQUIRED_LOCALES:
        assert order.body[locale.value].strip()


async def test_the_cap_category_follows_the_hazard(catalogue, directory, dispatcher) -> None:
    """A consumer filtering CAP on category gets the right answer without SARANA writing
    them an adapter, which is the whole reason for emitting CAP at all."""
    graph = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        divisions=[division(DIVISION, impact_class=3)],
    )

    values, _ = await run(
        graph,
        subject=warning.subject_for(EVENT, 3),
        payload={"hazard_event_id": EVENT, "hazard_type": "LANDSLIDE"},
    )

    assert "Geo" in values["validation"]["cap_xml"]


async def test_a_forecast_below_the_threshold_sends_nothing_and_says_so(
    catalogue, directory, dispatcher
) -> None:
    """ "No alert was needed" and "the agent fell over" have to be distinguishable from
    outside."""
    graph = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        divisions=[division(DIVISION, impact_class=1)],
    )

    values, _ = await run(graph, subject=EVENT)

    assert values["output"]["alert_needed"] is False
    assert "below" in values["output"]["reasoning"]
    assert not dispatcher.orders


async def test_divisions_at_other_bands_are_named_rather_than_folded_in(
    catalogue, directory, dispatcher
) -> None:
    """One alert never covers two impact classes.

    Sending the class 4 text to everybody tells a watch-level division to evacuate; sending
    the class 2 text tells a division in severe trouble to monitor water levels. Both
    destroy the thing that makes a warning work.
    """
    directory.targets = [
        household(1, "LK-21-01-001"),
        household(2, "LK-21-01-002"),
    ]
    graph = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        divisions=[
            division("LK-21-01-001", impact_class=4),
            division("LK-21-01-002", impact_class=2),
        ],
    )

    values, _ = await run(
        graph,
        subject=warning.subject_for(EVENT, 4),
        payload={
            "hazard_event_id": EVENT,
            "hazard_type": "FLOOD",
            "shelter_name": "Gampola Maha Vidyalaya",
        },
    )

    assert values["output"]["divisions"] == 1
    assert values["output"]["deferred_bands"] == {"class_2": 1}


# ---------------------------------------------------------------------------------------
# The human gate
# ---------------------------------------------------------------------------------------


async def test_an_alert_with_free_text_cannot_reach_dispatched_without_a_signoff(
    catalogue, directory, dispatcher
) -> None:
    """The headline requirement of build file 14.

    Template text has been through native review in three languages. Anything else stops
    and waits for a named DMC operator - and the run reports INTERRUPTED rather than
    quietly sending.
    """
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(
        graph,
        subject=warning.subject_for(EVENT, 3),
        payload={
            "hazard_event_id": EVENT,
            "hazard_type": "FLOOD",
            "free_text": {"en": "The Peradeniya bridge is closed."},
        },
    )

    assert values["__interrupt__"]
    assert not dispatcher.orders


async def test_a_signed_off_free_text_alert_dispatches(catalogue, directory, dispatcher) -> None:
    """The other half: the gate has to be passable, or an operator cannot say anything the
    templates do not cover."""
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)
    subject = warning.subject_for(EVENT, 3)

    _, config = await run(
        graph,
        subject=subject,
        payload={
            "hazard_event_id": EVENT,
            "hazard_type": "FLOOD",
            "free_text": {"en": "The Peradeniya bridge is closed."},
        },
    )

    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dmc-officer-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
            }
        ),
        config,
    )

    assert resumed["status"] == "COMPLETED"
    assert dispatcher.orders
    assert dispatcher.orders[0].free_text == {"en": "The Peradeniya bridge is closed."}
    assert resumed["output"]["provenance"] == "HUMAN"


async def test_text_authored_in_a_resume_is_never_dispatched(
    catalogue, directory, dispatcher
) -> None:
    """An approval answers the question that was asked; it is not a channel for new copy.

    `validate` has already built and checked the CAP document by the time the interrupt
    fires. Text added in the resume would reach a district having passed no trilingual
    check, no CAP validation and no segment measurement - so it is refused, and an operator
    who wants to say something the templates do not cover drafts it in the console, where
    file 09's own gate validates it before anybody signs.
    """
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)
    subject = warning.subject_for(EVENT, 3)

    _, config = await run(
        graph,
        subject=subject,
        payload={
            "hazard_event_id": EVENT,
            "hazard_type": "FLOOD",
            "free_text": {"en": "The Peradeniya bridge is closed."},
        },
    )

    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dmc-officer-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
                "free_text": {"en": "Also the Katugastota road has gone."},
            }
        ),
        config,
    )

    assert resumed["status"] == "COMPLETED"
    sent = dispatcher.orders[0]
    assert sent.free_text == {"en": "The Peradeniya bridge is closed."}
    assert "Katugastota" not in sent.body["en"]


async def test_a_refusal_is_a_decision_and_nothing_is_sent(
    catalogue, directory, dispatcher
) -> None:
    """ "No" is a decision, not an absence, and it is not retried."""
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)
    subject = warning.subject_for(EVENT, 3)

    _, config = await run(
        graph,
        subject=subject,
        payload={
            "hazard_event_id": EVENT,
            "hazard_type": "FLOOD",
            "free_text": {"en": "unreviewed text"},
        },
    )

    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dmc-officer-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": False,
            }
        ),
        config,
    )

    assert not dispatcher.orders
    assert resumed["output"]["alert_needed"] is False


async def test_the_gated_dispatch_tool_refuses_an_approval_for_another_subject() -> None:
    """The second layer, independent of the graph's routing.

    An approval for hazard event A carried into a dispatch about hazard event B is the
    realistic failure - a copied state key, a resume on the wrong thread - and comparing
    the ids is what makes an approval specific rather than ambient.
    """
    state = initial_state(
        agent="warning",
        subject_type="hazard_event",
        subject_id="evt-b",
        correlation_id="c",
    )
    state["human_decision"] = {
        "subject_id": "evt-a",
        "decided_by": "dmc-officer-1",
        "decided_at": datetime.now(UTC).isoformat(),
        "approved": True,
    }

    with pytest.raises(HumanGateMissing):
        await TOOLS.invoke("dispatch_free_text_warning", state, dispatcher=None, order=None)


def test_only_the_free_text_dispatch_tool_is_gated() -> None:
    """A gate over the template path would mean a fully reviewed evacuation order waits for
    somebody to be awake."""
    assert "dispatch_free_text_warning" in TOOLS.gated()
    assert "dispatch_templated_warning" not in TOOLS.gated()
    assert "dispatch_templated_warning" in TOOLS.side_effecting()


async def test_an_operator_can_answer_no_suitable_template_by_naming_one(
    catalogue, directory, dispatcher
) -> None:
    """The hand-off has to complete, or `no_suitable_template` is a dead end with a queue
    item on the front of it.

    A class 4 flood with no shelter named cannot fill the evacuation template. The operator
    knows the district and names the watch-level one they want instead; the run picks it up
    and goes on to dispatch.
    """
    graph = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        divisions=[division(DIVISION, impact_class=4)],
    )
    subject = warning.subject_for(EVENT, 4)

    paused, config = await run(graph, subject=subject)
    assert paused["__interrupt__"]

    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dmc-officer-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
                "template_code": "FLOOD_WARNING",
            }
        ),
        config,
    )

    assert resumed["status"] == "COMPLETED"
    assert resumed["output"]["template_code"] == "FLOOD_WARNING"
    assert dispatcher.orders[0].template_code == "FLOOD_WARNING"


async def test_no_suitable_template_asks_a_person_without_targeting_anybody(
    catalogue, directory, dispatcher
) -> None:
    """Resolving targets for an alert that has no text would read every household row in
    the area to build a fan-out nothing can be sent over."""
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(
        graph,
        subject=warning.subject_for(EVENT, 3),
        payload={"hazard_event_id": EVENT, "hazard_type": "DROUGHT"},
    )

    assert values["__interrupt__"]
    assert directory.calls == 0


# ---------------------------------------------------------------------------------------
# Quiet hours, fatigue and failure, through the whole graph
# ---------------------------------------------------------------------------------------


async def test_quiet_hours_hold_at_moderate_impact_and_are_bypassed_at_major(
    catalogue, directory, dispatcher
) -> None:
    """Required by build file 14, asserted through the graph rather than the rule alone.

    A rule that held in a unit test and was never consulted by the node would pass one and
    fail the district.
    """
    at_night = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        now=NIGHT_COLOMBO,
        divisions=[division(DIVISION, impact_class=2)],
    )
    watch, _ = await run(at_night, subject=warning.subject_for(EVENT, 2))

    assert "SMS" not in watch["plan"]["channels"]
    assert "SMS" in watch["plan"]["deferred"]

    graph = build_graph(
        catalogue=catalogue,
        directory=directory,
        dispatcher=dispatcher,
        now=NIGHT_COLOMBO,
        divisions=[division(DIVISION, impact_class=3)],
    )
    warning_level, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert "SMS" in warning_level["plan"]["channels"]


async def test_a_household_already_warned_at_this_level_is_not_messaged_again(
    catalogue, directory, dispatcher
) -> None:
    history = FakeHistory(
        priors=[
            PriorAlert(
                household_id="hh-1",
                hazard_event_id=EVENT,
                impact_class=3,
                sent_at=NOON_COLOMBO - timedelta(minutes=30),
            )
        ]
    )
    graph = build_graph(
        catalogue=catalogue, directory=directory, dispatcher=dispatcher, history=history
    )

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert values["target_summary"]["suppressed_for_fatigue"] == 1
    assert values["target_summary"]["targeted"] == 9


async def test_one_dead_channel_does_not_stop_the_others_and_shows_in_the_gaps(
    catalogue, directory, dispatcher
) -> None:
    """Required by build file 14: with one adapter failing 100%, the other channels still
    complete and the gaps report shows the failure accurately."""
    dispatcher.dead_channels = frozenset({"SMS"})
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert values["status"] == "COMPLETED"
    assert values["output"]["confirmed"] == 10
    assert values["dispatched"]["channels_failed"] == ["SMS"]


async def test_an_alert_over_the_target_cap_is_not_dispatched(
    catalogue, directory, dispatcher
) -> None:
    """A misconfigured area selection has to be stopped before twenty million messages."""
    graph = build_graph(
        catalogue=catalogue, directory=directory, dispatcher=dispatcher, target_cap=5
    )

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert not values["validation"]["dispatchable"]
    assert not dispatcher.orders


async def test_unreachable_households_reach_the_gap_report(catalogue, dispatcher) -> None:
    """They are the people who need a vehicle with a loudhailer, and the count is the input
    to that decision."""
    directory = FakeDirectory(
        targets=[
            *(household(index, DIVISION) for index in range(1, 8)),
            *(household(index, DIVISION, reachable=False) for index in range(8, 11)),
        ],
        coverage={DIVISION: 40.0},
    )
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert values["output"]["no_channel_available"] == 3
    assert values["gap_report"]["no_channel_available"] == 3
    assert "with no channel available" in values["output"]["delivery_summary"]


# ---------------------------------------------------------------------------------------
# Degraded paths and identity
# ---------------------------------------------------------------------------------------


async def test_the_whole_agent_runs_with_no_model_provider(
    catalogue, directory, dispatcher
) -> None:
    """The degraded path is the ordinary path. Every test in this file runs with `call=None`,
    and this one says so out loud."""
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))

    assert values["status"] == "COMPLETED"
    assert values["output"]["provenance"] == "DETERMINISTIC"
    assert values["selection"]["method"] == "RULE_MATRIX"


def test_the_subject_id_round_trips_through_the_band() -> None:
    """A resume derives its thread from the subject and never has to search for it."""
    subject = warning.subject_for(EVENT, 4)

    assert warning.event_and_class(subject) == (EVENT, 4)
    assert warning.event_and_class(EVENT) == (EVENT, None)


def test_the_thread_id_survives_the_resume_endpoints_splitter() -> None:
    """The resume endpoint splits on the first two colons only, so the band must not add a
    third."""
    from agent_svc.api.v1.agents import _split_thread_id

    subject = warning.subject_for(EVENT, 4)
    thread = f"warning:hazard_event:{subject}"

    assert _split_thread_id(thread) == ("warning", "hazard_event", subject)


async def test_a_graph_with_no_dependencies_refuses_rather_than_reporting_a_quiet_day() -> None:
    """The worst available way for a warning service to be broken is to complete
    successfully having sent nothing."""
    graph = warning.build(memory_checkpointer())

    with pytest.raises(RuntimeError, match="forecast source"):
        await run(graph, subject=warning.subject_for(EVENT, 3))


async def test_a_dispatched_body_is_measured_against_the_sms_segment_limit(
    catalogue, directory, dispatcher
) -> None:
    """Recorded, not refused. Refusing to send a warning because a long division name pushed
    it three characters over would trade a real warning for a tidy one."""
    graph = build_graph(catalogue=catalogue, directory=directory, dispatcher=dispatcher)

    values, _ = await run(graph, subject=warning.subject_for(EVENT, 3))
    order = dispatcher.orders[0]

    assert values["validation"]["oversized_sms"] == {}
    assert all(sms.fits(text) for text in order.body.values())


def test_the_spec_declares_the_agent_gated_and_says_what_a_blackout_costs() -> None:
    """`GET /agents` tells an operator which agents can pause on a human before anybody has
    to read the graph."""
    assert warning.SPEC.gated is True
    assert warning.SPEC.subject_type == "hazard_event"
    assert "matrix" in warning.SPEC.degraded_note
