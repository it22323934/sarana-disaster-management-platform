"""Priority scoring, ageing, and the routing that a blocked road changes.

Two properties carry this file.

**Ageing.** An incident that sits unrescued must rise, or a queue sorted on severity starves
every moderate incident for the whole event — the medical calls keep arriving, they keep
outranking the family on the roof, and that family is still there on day three.

**A blocked road changes the plan.** It is the one place the impact forecast reaches the
routing, and it is what turns "slow to reach" into "unservable", which is the distinction a
dispatcher escalates on.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.triage import routing, scoring
from agent_svc.agents.triage.ports import RESPONDER_TYPES
from incident_svc.domain import triage as file08
from incident_svc.repo.dispatch import RESPONDER_TYPES as SCHEMA_RESPONDER_TYPES
from tests.agents.triage.conftest import (
    DELTOTA,
    GAMPOLA,
    KANDY,
    PERADENIYA,
    incident,
    responder,
)


def factors(incident_id: str, **kwargs) -> scoring.TriageFactors:
    base = {"incident_id": incident_id, "incident_type": "FLOOD"}
    return scoring.TriageFactors(**{**base, **kwargs})


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def test_immediate_danger_is_the_heaviest_single_factor() -> None:
    """Build file 16 requires it. It is the one term that says somebody is dying now."""
    assert max(scoring._WEIGHTS.values()) == scoring.WEIGHT_IMMEDIATE_DANGER


def test_the_weights_sum_to_one_so_the_score_reads_as_a_fraction() -> None:
    assert sum(scoring._WEIGHTS.values()) == pytest.approx(1.0)


def test_a_report_that_did_not_state_a_count_is_scored_as_one_person() -> None:
    """`None` means the report did not say - intake refuses to guess - and scoring it as
    zero would sort a real emergency below every incident that mentioned a number."""
    unstated = factors("i1", people_at_risk=None)

    assert unstated.people == 1


def test_vulnerability_is_a_maximum_not_a_sum() -> None:
    """A household with an infant and a grandparent is not twice as urgent as one with
    either, and adding them would let composition outweigh how many people are in danger."""
    one = scoring.vulnerability_factor(("elderly",))
    both = scoring.vulnerability_factor(("elderly", "children"))

    assert one == both


def test_an_incident_that_waits_rises_up_the_queue() -> None:
    """The ageing property, stated at its simplest."""
    fresh = factors("fresh", minutes_since_report=0)
    waited = factors("waited", minutes_since_report=90)

    model = scoring.WeightedSumModel()

    assert model.score(waited).score > model.score(fresh).score


def test_a_moderate_incident_at_ninety_minutes_outranks_a_fresh_moderate_one() -> None:
    """Required by build file 16, and the exact case that stops starvation."""
    queue = [
        factors("fresh", incident_type="FLOOD", people_at_risk=2, minutes_since_report=0),
        factors("waited", incident_type="FLOOD", people_at_risk=2, minutes_since_report=90),
    ]

    ranked = scoring.rank(queue)

    assert [item.incident_id for item in ranked] == ["waited", "fresh"]


def test_ageing_saturates_so_an_old_supply_request_cannot_outrank_a_fresh_rescue() -> None:
    """The opposite failure, and harder to notice because the queue still looks busy.

    An unbounded age term eventually lets a four-hour-old supply request outrank a fresh
    medical call.
    """
    old_supplies = factors(
        "supplies", incident_type="SUPPLIES_NEEDED", people_at_risk=1, minutes_since_report=600
    )
    fresh_medical = factors(
        "medical",
        incident_type="MEDICAL",
        people_at_risk=1,
        minutes_since_report=0,
        immediate_danger=True,
    )

    ranked = scoring.rank([old_supplies, fresh_medical])

    assert ranked[0].incident_id == "medical"


def test_the_age_curve_is_flat_past_saturation() -> None:
    at_saturation = scoring.age_factor(file08.AGE_SATURATION_MINUTES)
    well_past = scoring.age_factor(file08.AGE_SATURATION_MINUTES * 10)

    assert at_saturation == well_past == 1.0


def test_low_location_confidence_reduces_dispatchability_not_urgency() -> None:
    """Build file 16 is precise about this and it matters: a report nobody can place is
    exactly as urgent as one with a GPS fix. Somebody is still in the water.

    Folding the two would quietly deprioritise the people whose reports the platform serves
    worst, which is the population it exists for.
    """
    model = scoring.WeightedSumModel()
    placed = model.score(factors("placed", location_confidence=1.0))
    unplaced = model.score(factors("unplaced", location_confidence=0.1))

    assert placed.score == unplaced.score
    assert unplaced.dispatchability < placed.dispatchability
    assert not unplaced.dispatchable


def test_corroboration_is_the_lightest_factor() -> None:
    """A household that only called once is not in less danger than one whose neighbours
    also called - they may have one phone between them."""
    assert min(scoring._WEIGHTS.values()) == scoring.WEIGHT_CORROBORATION


def test_the_breakdown_names_every_term_and_its_weight() -> None:
    """A ranking a dispatcher cannot interrogate is one they over-trust or ignore."""
    result = scoring.WeightedSumModel().score(factors("i1", immediate_danger=True))

    assert set(result.factors["terms"]) == set(scoring._WEIGHTS)
    assert result.factors["weights"] == scoring._WEIGHTS
    assert "immediate_danger" in result.explanation()


def test_ties_break_on_age_so_the_queue_does_not_reorder_under_a_dispatcher() -> None:
    """Without a stated tie-break the order of two equally urgent incidents depends on what
    the database returned, so a dispatcher refreshing sees them swap."""
    identical = [
        factors("b", people_at_risk=2, minutes_since_report=10),
        factors("a", people_at_risk=2, minutes_since_report=30),
    ]

    ranked = scoring.rank(identical)

    assert [item.incident_id for item in ranked] == ["a", "b"]


def test_the_age_saturation_is_shared_with_file_08() -> None:
    """Two scorers that aged incidents at different rates would disagree about the same
    queue depending on which one produced it."""
    assert scoring.age_factor(file08.AGE_SATURATION_MINUTES) == 1.0


def test_the_incident_type_weights_are_file_08s() -> None:
    result = scoring.WeightedSumModel().score(factors("i1", incident_type="MEDICAL"))

    assert result.factors["terms"]["incident_type"] == file08.INCIDENT_TYPE_WEIGHTS["MEDICAL"]


def test_the_score_is_a_rule_and_says_so() -> None:
    """Do not ship an untrained model and call it ML."""
    result = scoring.WeightedSumModel().score(factors("i1"))

    assert result.method == "WEIGHTED_SUM"
    assert result.model_version.startswith("rule-")


# ---------------------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------------------


SOLVERS = [routing.GreedySolver(), routing.OrToolsSolver()]
SOLVER_IDS = ["greedy", "ortools"]


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_a_responder_is_assigned_to_a_reachable_incident(solver) -> None:
    plan = solver.solve(
        [incident("i1", at=GAMPOLA, people=2)],
        [responder("r1", at=KANDY, capacity=6)],
        time_limit_s=2.0,
    )

    assert plan.served == ["i1"]
    assert not plan.unservable


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_an_incident_with_no_coordinate_is_named_unservable_never_dropped(solver) -> None:
    """Required by build file 16. An unservable incident is critical information - it is the
    one a dispatcher escalates - and a plan that quietly omitted it would look complete."""
    plan = solver.solve(
        [incident("placed", at=GAMPOLA), incident("unplaced", at=None)],
        [responder("r1", at=KANDY)],
        time_limit_s=2.0,
    )

    assert "unplaced" not in plan.served
    assert [item.reason for item in plan.unservable] == [routing.REASON_NO_LOCATION]


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_a_flood_blocked_division_cannot_be_reached_by_a_road_vehicle(solver) -> None:
    """The one place the impact forecast reaches the routing.

    A jeep does not drive into a division whose roads are under water, and the incident is
    unservable rather than slow - which is what a dispatcher escalates to another agency.
    """
    plan = solver.solve(
        [incident("cut-off", at=DELTOTA, road_access_lost=True)],
        [responder("jeep", responder_type="MEDICAL_TEAM", at=KANDY)],
        time_limit_s=2.0,
    )

    assert plan.served == []
    assert plan.unservable[0].reason == routing.REASON_NO_CAPABLE_RESPONDER


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_a_boat_can_reach_a_flood_blocked_division(solver) -> None:
    """The other half. Without it the rule would just be "never serve a flooded division"."""
    plan = solver.solve(
        [incident("cut-off", at=DELTOTA, road_access_lost=True)],
        [responder("boat", responder_type="NAVY", at=KANDY)],
        time_limit_s=2.0,
    )

    assert plan.served == ["cut-off"]


def test_a_blocked_road_changes_which_responder_is_sent() -> None:
    """Required by build file 16: a flood-blocked edge changes the computed route.

    With roads intact the nearer land team goes. With the roads gone it cannot, and the
    boat does - a different plan from the same incident.
    """
    crews = [
        responder("land", responder_type="MEDICAL_TEAM", at=PERADENIYA),
        responder("boat", responder_type="NAVY", at=KANDY),
    ]
    solver = routing.GreedySolver()

    open_road = solver.solve([incident("i1", at=GAMPOLA)], crews, time_limit_s=2.0)
    blocked = solver.solve(
        [incident("i1", at=GAMPOLA, road_access_lost=True)], crews, time_limit_s=2.0
    )

    assert open_road.routes[0].responder_id == "land"
    assert blocked.routes[0].responder_id == "boat"


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_an_incident_larger_than_every_available_capacity_is_named(solver) -> None:
    plan = solver.solve(
        [incident("big", at=GAMPOLA, people=40)],
        [responder("small", at=KANDY, capacity=4)],
        time_limit_s=2.0,
    )

    assert plan.served == []
    assert plan.unservable[0].reason == routing.REASON_NO_CAPACITY


@pytest.mark.parametrize("solver", SOLVERS, ids=SOLVER_IDS)
def test_capacity_is_respected_across_a_multi_stop_route(solver) -> None:
    """A crew of six does not rescue ten people in one trip."""
    plan = solver.solve(
        [
            incident("a", at=GAMPOLA, people=4),
            incident("b", at=PERADENIYA, people=4),
            incident("c", at=DELTOTA, people=4),
        ],
        [responder("r1", at=KANDY, capacity=8)],
        time_limit_s=2.0,
    )

    assert len(plan.served) <= 2
    assert len(plan.unservable) >= 1


def test_the_estimated_duration_is_the_longest_route_not_the_sum() -> None:
    """The routes run concurrently. Summing them would tell a dispatcher a plan takes six
    hours when every crew is home in ninety minutes."""
    plan = routing.GreedySolver().solve(
        [incident("a", at=GAMPOLA, people=2), incident("b", at=DELTOTA, people=2)],
        [responder("r1", at=KANDY, capacity=2), responder("r2", at=PERADENIYA, capacity=2)],
        time_limit_s=2.0,
    )

    assert plan.estimated_duration_min == int(max(route.total_minutes for route in plan.routes))


def test_a_faster_responder_reaches_an_incident_sooner() -> None:
    """The travel model is mode-aware. An ambulance on a road is quicker than a boat.

    The detour factor is the module's admission that there is no road network, and it
    applies to every mode here because every one of them is on a road or a river.
    """
    travel = routing.TravelModel()
    ambulance = responder("a", responder_type="AMBULANCE", at=KANDY)
    boat = responder("b", responder_type="NAVY", at=KANDY)

    assert travel.minutes(ambulance, *KANDY, *GAMPOLA) < travel.minutes(boat, *KANDY, *GAMPOLA)


def test_the_greedy_fallback_is_always_available_and_labels_itself() -> None:
    """OR-Tools is a native dependency that can be absent. An agent whose only routing path
    needs it is one that stops planning when it is missing."""
    plan = routing.GreedySolver().solve(
        [incident("i1", at=GAMPOLA)], [responder("r1", at=KANDY)], time_limit_s=2.0
    )

    assert plan.method == routing.METHOD_GREEDY


def test_the_ortools_solver_labels_its_own_output() -> None:
    """A dispatcher looking at a worse plan should know it is a worse plan."""
    plan = routing.OrToolsSolver().solve(
        [incident("i1", at=GAMPOLA)], [responder("r1", at=KANDY)], time_limit_s=2.0
    )

    assert plan.method == routing.METHOD_ORTOOLS


def test_ortools_sequences_a_route_at_least_as_well_as_greedy() -> None:
    """What OR-Tools is actually for. Greedy takes the nearest next incident; the solver
    considers the whole tour, so it is never worse on total travel."""
    incidents = [
        incident("a", at=GAMPOLA, people=1),
        incident("b", at=PERADENIYA, people=1),
        incident("c", at=DELTOTA, people=1),
    ]
    crews = [responder("r1", at=KANDY, capacity=10)]

    greedy = routing.GreedySolver().solve(incidents, crews, time_limit_s=2.0)
    solved = routing.OrToolsSolver().solve(incidents, crews, time_limit_s=3.0)

    assert len(solved.served) >= len(greedy.served)
    if len(solved.served) == len(greedy.served) == len(incidents):
        assert solved.estimated_duration_min <= greedy.estimated_duration_min + 1


def test_an_unavailable_responder_is_not_assigned() -> None:
    plan = routing.GreedySolver().solve(
        [incident("i1", at=GAMPOLA)],
        [responder("busy", at=KANDY, status="EN_ROUTE")],
        time_limit_s=2.0,
    )

    assert plan.served == []


def test_the_responder_vocabulary_matches_the_column_that_stores_it() -> None:
    """A type this agent plans with and `incident.responder` rejects would fail at the
    INSERT, after a dispatcher approved the plan."""
    assert set(RESPONDER_TYPES) == set(SCHEMA_RESPONDER_TYPES)


def test_every_water_or_air_capable_type_is_a_real_responder_type() -> None:
    from agent_svc.agents.triage.ports import WATER_OR_AIR_CAPABLE

    assert set(RESPONDER_TYPES) >= WATER_OR_AIR_CAPABLE
