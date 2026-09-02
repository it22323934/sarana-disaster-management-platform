"""The dispatch gate, asserted at every layer that holds it independently.

Build file 16 names this file in its definition of done, and it is the most important test
in the agent. Committing a dispatch sends people towards a hazard. No model, no
configuration and no code path may do it alone.

Four layers, and each is tested here on its own terms rather than through the others:

  1. **The graph.** A plan cannot reach `released` without a resume carrying an approval.
  2. **The tool registry.** `release_dispatch_plan` is gated, and refuses a decision that
     names a different subject.
  3. **The scope model.** `Scope.DISPATCH_COMMIT` is stripped from every machine principal
     at mint time, so no agent can hold it however it is configured.
  4. **The gate function.** `dispatch_gate.approve` is the only writer of `signed_off_by`
     and requires a second factor verified inside the step-up window.

The database trigger is the fifth and is asserted in `tests/schema`, where a live Postgres
is available.

Testing them separately is the point. Four layers that could only be tested through each
other would be one layer wearing four hats.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langgraph.types import Command

from agent_svc.agents.triage import graph as triage
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.errors import HumanGateMissing
from agent_svc.runtime.state import initial_state
from agent_svc.runtime.tools import REGISTRY as TOOLS
from incident_svc.domain import dispatch_gate
from sarana_shared.auth.grants import ScopeGrant, ScopeType, strip_human_gates
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from tests.agents.triage.conftest import (
    KANDY,
    NOW,
    FakeIncidents,
    FakePlanStore,
    FakeResponders,
    incident,
    responder,
)


def build_graph(store: FakePlanStore, **kwargs):
    return triage.build(
        memory_checkpointer(),
        incidents=FakeIncidents(queue=[incident("i1", people=2)]),
        responders=FakeResponders(crews=[responder("r1", at=KANDY)]),
        store=store,
        now=NOW,
        **kwargs,
    )


async def run(graph, *, subject: str = "plan-run-1"):
    state = initial_state(
        agent="triage",
        subject_type="dispatch_plan",
        subject_id=subject,
        correlation_id="test-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    config = config_for(f"triage:dispatch_plan:{subject}")
    return await graph.ainvoke(state, config), config


# ---------------------------------------------------------------------------------------
# Layer 1: the graph
# ---------------------------------------------------------------------------------------


async def test_a_plan_pauses_at_the_gate_and_releases_nothing(store: FakePlanStore) -> None:
    """The plan is written PROPOSED and the graph stops. Nothing is released."""
    graph = build_graph(store)

    values, _ = await run(graph)

    assert values["__interrupt__"]
    assert store.proposed
    assert not values.get("released")


async def test_a_plan_cannot_reach_released_without_a_resume(store: FakePlanStore) -> None:
    """There is no path through the graph that reaches `release` on the agent's authority.

    The run halts at the interrupt and stays halted. It survives here at zero cost - the
    checkpointer holds it - and nothing downstream has been told a dispatch happened.
    """
    graph = build_graph(store)

    values, config = await run(graph)

    assert values["__interrupt__"]

    # Re-invoking without a decision does not push it past the gate.
    again = await graph.ainvoke(None, config)
    assert again.get("__interrupt__")
    assert not again.get("released")


async def test_an_approval_releases_and_records_who_decided(store: FakePlanStore) -> None:
    """The gate has to be passable, or a dispatcher cannot dispatch."""
    graph = build_graph(store)
    subject = "plan-run-approve"

    _, config = await run(graph, subject=subject)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dispatcher-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
            }
        ),
        config,
    )

    assert resumed["output"]["released"] is True
    assert resumed["output"]["decided_by"] == "dispatcher-1"
    # A person decided. Never DETERMINISTIC and never MODEL.
    assert resumed["output"]["provenance"] == "HUMAN"


async def test_a_rejection_releases_nothing_and_is_recorded(store: FakePlanStore) -> None:
    """A rejection is a decision and the most valuable data the platform produces."""
    graph = build_graph(store)
    subject = "plan-run-reject"

    _, config = await run(graph, subject=subject)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": subject,
                "decided_by": "dispatcher-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": False,
                "reason": "wrong_priority",
                "note": "the school is already evacuated",
            }
        ),
        config,
    )

    assert resumed["output"]["released"] is False
    assert resumed["output"]["rejection_reason"] == "wrong_priority"
    assert store.rejected[0]["reason"] == "wrong_priority"


# ---------------------------------------------------------------------------------------
# Layer 2: the tool registry
# ---------------------------------------------------------------------------------------


def test_the_release_tool_is_gated_and_side_effecting() -> None:
    assert "release_dispatch_plan" in TOOLS.gated()
    assert "release_dispatch_plan" in TOOLS.side_effecting()


async def test_the_release_tool_refuses_with_no_decision_at_all() -> None:
    state = initial_state(
        agent="triage", subject_type="dispatch_plan", subject_id="plan-a", correlation_id="c"
    )

    with pytest.raises(HumanGateMissing, match="needs a human decision"):
        await TOOLS.invoke(
            "release_dispatch_plan", state, store=None, plan_id="plan-a", decision={}
        )


async def test_the_release_tool_refuses_an_approval_for_another_plan() -> None:
    """The realistic failure: an approval carried from one plan to another by a copied state
    key or a resume on the wrong thread. Comparing the ids is what makes an approval
    specific rather than ambient."""
    state = initial_state(
        agent="triage", subject_type="dispatch_plan", subject_id="plan-b", correlation_id="c"
    )
    state["human_decision"] = {
        "subject_id": "plan-a",
        "decided_by": "dispatcher-1",
        "decided_at": datetime.now(UTC).isoformat(),
        "approved": True,
    }

    with pytest.raises(HumanGateMissing, match="approves subject"):
        await TOOLS.invoke(
            "release_dispatch_plan", state, store=None, plan_id="plan-b", decision={}
        )


async def test_the_release_tool_refuses_a_recorded_refusal() -> None:
    """A refusal is a decision, not an absence, and it is not retried into an approval."""
    state = initial_state(
        agent="triage", subject_type="dispatch_plan", subject_id="plan-c", correlation_id="c"
    )
    state["human_decision"] = {
        "subject_id": "plan-c",
        "decided_by": "dispatcher-1",
        "decided_at": datetime.now(UTC).isoformat(),
        "approved": False,
    }

    with pytest.raises(HumanGateMissing, match="said no"):
        await TOOLS.invoke(
            "release_dispatch_plan", state, store=None, plan_id="plan-c", decision={}
        )


# ---------------------------------------------------------------------------------------
# Layer 3: the scope model
# ---------------------------------------------------------------------------------------


def test_dispatch_commit_is_a_human_gate_scope() -> None:
    assert Scope.DISPATCH_COMMIT in HUMAN_GATE_SCOPES


def test_no_machine_principal_can_hold_dispatch_commit() -> None:
    """Stripped at mint time, so no configuration mistake and no role misassignment can
    hand an agent the ability to commit a dispatch."""
    assert Scope.DISPATCH_COMMIT not in ROLE_SCOPES[Role.AGENT]


def test_stripping_removes_dispatch_commit_from_any_grant_set() -> None:
    """Asserted against the function itself, not only against the AGENT role.

    A future role that was given the scope by mistake still cannot keep it.
    """
    granted = frozenset(
        {
            ScopeGrant(
                scope=Scope.DISPATCH_COMMIT, scope_type=ScopeType.DISTRICT, scope_code="LK-21"
            ),
            ScopeGrant(
                scope=Scope.INCIDENT_READ, scope_type=ScopeType.DISTRICT, scope_code="LK-21"
            ),
        }
    )

    stripped = strip_human_gates(granted)

    assert all(grant.scope is not Scope.DISPATCH_COMMIT for grant in stripped)
    assert any(grant.scope is Scope.INCIDENT_READ for grant in stripped)


def test_the_triage_agent_declares_itself_gated() -> None:
    """`GET /agents` tells an operator which agents pause on a person before anybody has to
    read the graph."""
    assert triage.SPEC.gated is True


# ---------------------------------------------------------------------------------------
# Layer 4: the gate function
# ---------------------------------------------------------------------------------------


def _principal(*, stepped_up_minutes_ago: float | None) -> Principal:
    """A dispatcher who holds the scope. The only thing varied is their second factor."""
    step_up = (
        None
        if stepped_up_minutes_ago is None
        else datetime.now(UTC) - timedelta(minutes=stepped_up_minutes_ago)
    )
    return Principal(
        subject_id=str(uuid4()),
        roles=frozenset({Role.DMC_OPERATOR}),
        grants=frozenset(
            {
                ScopeGrant(
                    scope=Scope.DISPATCH_COMMIT, scope_type=ScopeType.DISTRICT, scope_code="LK-21"
                )
            }
        ),
        step_up_at=step_up,
    )


def test_the_gate_requires_a_second_factor() -> None:
    """A session alone is never sufficient. The person must have proved possession of their
    factor inside the window."""
    with pytest.raises(dispatch_gate.StepUpFailed):
        dispatch_gate.assert_step_up(_principal(stepped_up_minutes_ago=None))


def test_the_gate_refuses_a_stale_second_factor() -> None:
    with pytest.raises(dispatch_gate.StepUpFailed):
        dispatch_gate.assert_step_up(_principal(stepped_up_minutes_ago=60))


def test_the_gate_accepts_a_fresh_second_factor() -> None:
    dispatch_gate.assert_step_up(_principal(stepped_up_minutes_ago=1))


def test_the_gate_refuses_a_plan_that_already_carries_a_decision() -> None:
    """Approving twice is a double-click, not a second dispatch - and the second caller may
    be a different person who needs to know the decision was already made."""
    plan = {"id": uuid4(), "status": "RELEASED", "signed_off_by": uuid4()}

    with pytest.raises(dispatch_gate.AlreadyDecided):
        dispatch_gate.assert_undecided(plan)


def test_the_gate_allows_a_proposed_plan() -> None:
    dispatch_gate.assert_undecided({"id": uuid4(), "status": "PROPOSED", "signed_off_by": None})


def test_the_agents_rejection_reasons_are_the_gates_own() -> None:
    """Two taxonomies that were meant to match are two that eventually do not, and the one
    that silently wins is whichever the API validated against."""
    from agent_svc.agents.triage import rejections

    assert set(rejections.REASONS) == {reason.value for reason in dispatch_gate.RejectionReason}


# ---------------------------------------------------------------------------------------
# The agent has no way to release, by construction
# ---------------------------------------------------------------------------------------


def test_the_plan_store_port_has_no_release_method() -> None:
    """The strongest form of the guarantee: not "the agent does not call release" but
    "there is nothing for it to call".

    `PlanStore` offers `propose` and `record_rejection`. Releasing is
    `dispatch_gate.approve`, which lives in another service behind a scope the agent cannot
    hold.
    """
    from agent_svc.agents.triage.ports import PlanStore

    methods = {name for name in dir(PlanStore) if not name.startswith("_")}

    assert methods == {"propose", "record_rejection"}


async def test_a_proposed_plan_is_written_with_no_status_argument(store: FakePlanStore) -> None:
    """There is no argument the agent can pass that produces a released plan."""
    graph = build_graph(store)

    await run(graph)

    assert "status" not in store.proposed[0]
    assert "signed_off_by" not in store.proposed[0]
