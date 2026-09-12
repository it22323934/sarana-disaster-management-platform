"""The dispatch gate's reasoning payload, and what it must never fabricate.

Build file 20 requires the gate screen to render the per-incident factor breakdown and the
`unservable` list "expanded by default". Both have been in `incident.dispatch_plan.route`
since file 16 - the triage agent's `Plan.as_route_column()` writes exactly this shape -
and the response model was the only thing that did not expose them.

These tests are about the one way this can go wrong quietly. An empty factor list rendered
under a "why these are ranked here" heading reads as *the agent considered nothing*, which
is a different and much worse claim than *nothing recorded a reason*. So the distinction
between "no reasoning" and "empty reasoning" is a test rather than a convention.
"""

from __future__ import annotations

from typing import Any

from incident_svc.api.v1.dispatch import PlanReasoning, _reasoning_from


def a_route_column(**overrides: Any) -> dict[str, Any]:
    """What the triage agent writes. Kept in the shape `as_route_column()` produces."""
    column: dict[str, Any] = {
        "routes": [
            {
                "responder_id": "018f3c2a-0002-7e90-9c2d-000000000002",
                "stops": [
                    {
                        "incident_id": "018f3c2a-0001-7e90-9c2d-000000000001",
                        "sequence": 1,
                        "eta_minutes": 18.4,
                    }
                ],
                "total_minutes": 41.0,
            }
        ],
        "unservable": [
            {
                "incident_id": "018f3c2a-0007-7e90-9c2d-000000000007",
                "reason": "NO_CAPABLE_RESPONDER",
                "detail": "no boat-capable team within range",
            }
        ],
        "factors": [
            {
                "incident_id": "018f3c2a-0001-7e90-9c2d-000000000001",
                "rank": 1,
                "score": 0.82,
                "dispatchability": 0.9,
                "dispatchable": True,
                "model_version": "triage-rules-1",
                "method": "RULE",
                "factors": {"contributions": {"people_at_risk": 0.41, "severity": 0.3}},
                "explanation": "42 people at risk in a division with road access lost",
            }
        ],
        "method": "ORTOOLS",
        "status": "OPTIMAL",
        "rationale": "Two teams cover four incidents; one needs a boat and has none.",
        "rationale_method": "TEMPLATE",
    }
    column.update(overrides)
    return column


def test_a_plan_with_no_route_column_has_no_reasoning_rather_than_empty_reasoning() -> None:
    """None and an empty object are different claims, and the console renders them apart.

    A plan proposed by something that recorded nothing has no reasoning. An empty
    `PlanReasoning` would put an empty factor list under a "why these are ranked here"
    heading, which tells a dispatcher the agent weighed nothing - and that is the sentence
    that makes a gate screen actively misleading rather than merely incomplete.
    """
    assert _reasoning_from(None) is None
    assert _reasoning_from({}) is None
    # Not a mapping at all. A column written by something that got the shape wrong is
    # absent reasoning, not a 500 on the one screen that must not fail.
    assert _reasoning_from("routes") is None
    assert _reasoning_from([{"routes": []}]) is None


def test_the_unservable_list_survives_the_round_trip() -> None:
    """The unservable list is the most decision-relevant thing on the gate screen.

    It is the incident the dispatcher escalates to a different agency. A plan that quietly
    dropped it would look complete while somebody waited for a team that was never coming.
    """
    reasoning = _reasoning_from(a_route_column())
    assert reasoning is not None
    assert [item.incident_id for item in reasoning.unservable] == [
        "018f3c2a-0007-7e90-9c2d-000000000007"
    ]
    assert reasoning.unservable[0].reason == "NO_CAPABLE_RESPONDER"
    assert reasoning.unservable[0].detail == "no boat-capable team within range"


def test_a_factor_name_the_console_has_never_seen_is_carried_through() -> None:
    """`factors` stays a free-shaped mapping because the triage model owns its names.

    Pinning the keys here would mean a model that added a term produced a validation error
    on the gate screen. The screen renders what it is given and drops nothing, because the
    term it does not recognise is the one the model just started using.
    """
    column = a_route_column()
    column["factors"][0]["factors"]["contributions"]["newly_added_term"] = 0.17
    reasoning = _reasoning_from(column)
    assert reasoning is not None
    contributions = reasoning.factors[0].factors["contributions"]
    assert contributions["newly_added_term"] == 0.17


def test_a_column_written_before_a_key_existed_reads_as_empty_not_as_an_error() -> None:
    """Forecasts and plans outlive the code that wrote them.

    A `route` column from an older triage agent is missing keys this model names. Each one
    becomes an empty list, so a plan proposed last month still opens on the gate screen -
    which is the only place it can be decided.
    """
    reasoning = _reasoning_from({"routes": [{"responder_id": "r1"}]})
    assert reasoning is not None
    assert reasoning.unservable == []
    assert reasoning.factors == []
    assert reasoning.method is None
    assert reasoning.routes[0].responder_id == "r1"
    # A route with no stops is a responder assigned nothing, which is a real state.
    assert reasoning.routes[0].stops == []


def test_a_malformed_entry_is_skipped_rather_than_failing_the_whole_payload() -> None:
    """One bad row must not take the gate screen down with it."""
    column = a_route_column(unservable=["not-an-object", {"incident_id": "i1", "reason": "X"}])
    reasoning = _reasoning_from(column)
    assert reasoning is not None
    assert [item.incident_id for item in reasoning.unservable] == ["i1"]
    # `detail` is optional on the way in: an older writer recorded a reason and no prose.
    assert reasoning.unservable[0].detail == ""


def test_the_rationale_and_the_method_that_produced_it_travel_together() -> None:
    """A sentence with no attribution is a sentence a dispatcher cannot weigh.

    "TEMPLATE" and a model name mean different things about how much the prose can be
    trusted, and the screen shows both for the same reason the queue shows `ordering`.
    """
    reasoning = _reasoning_from(a_route_column())
    assert reasoning is not None
    assert reasoning.rationale_method == "TEMPLATE"
    assert reasoning.rationale is not None and reasoning.rationale.startswith("Two teams")


def test_the_reasoning_model_defaults_to_empty_lists_not_to_none() -> None:
    """Constructed with nothing, every collection is iterable.

    The console maps over these unconditionally. A `None` where a list is expected is a
    crash on the gate screen, and a crash on the gate screen is a gate nobody can pass.
    """
    empty = PlanReasoning()
    assert empty.routes == []
    assert empty.unservable == []
    assert empty.factors == []
