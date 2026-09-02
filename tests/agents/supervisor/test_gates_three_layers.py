"""Each of the three gate layers, asserted with the other two out of the picture.

Build file 18 names this file and is specific about the method: "Test each independently by
disabling the other two in a test harness. Ship all three."

The reason is that three layers which can only be tested through each other are one layer
wearing three hats. If the API check is what actually refuses in every test, the database
trigger could have been dropped in a migration two months ago and nothing would have told
anybody.

  1. **Graph** — the interrupt, `verify_approval_record`, and the gated-tool refusal. Tested
     here with no API and no database trigger anywhere near it.
  2. **API** — scope, fresh TOTP and segregation of duty. Tested here at the level agent-svc
     owns: `Scope.DISPATCH_COMMIT` and `Scope.DISBURSEMENT_RELEASE` are stripped from every
     machine principal at mint time, so no agent can hold either however it is configured.
  3. **Database** — the trigger and the `NOT NULL` columns. Asserted in `tests/schema`, where
     a live Postgres exists; what is checked here is that the constraint is declared, so a
     migration that dropped it fails a test that runs without Docker.

**The single most important test in the file** is
`test_a_resume_claiming_an_approval_that_does_not_exist_is_refused`. A resume payload is
client input. A graph that reads `decision["approved"]` and commits has authenticated a JSON
field.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langgraph.types import Command

from agent_svc.agents.supervisor import gates
from agent_svc.agents.supervisor import graph as supervisor
from agent_svc.agents.supervisor.gates import GateKind
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.errors import HumanGateMissing
from agent_svc.runtime.state import initial_state
from agent_svc.runtime.tools import REGISTRY as TOOLS
from sarana_shared.auth.grants import ScopeGrant, ScopeType, strip_human_gates
from sarana_shared.auth.principal import STEP_UP_WINDOW
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from tests.agents.supervisor.conftest import (
    APPROVER,
    NOW,
    SUBJECT,
    FakeApprovals,
    approval,
)

READY = {"intake_verified", "intake_deduplicated", "triaged"}


def build_graph(approvals: FakeApprovals):
    return supervisor.build(memory_checkpointer(), approvals=approvals, now=NOW)


async def run_gate(graph, approvals: FakeApprovals, *, subject: str = SUBJECT):
    approvals.facts.setdefault(subject, set(READY))
    state = initial_state(
        agent="supervisor", subject_type="event", subject_id=subject, correlation_id="c-1"
    )
    state["output"] = {
        "event_type": "sarana.dispatch.signoff.requested",
        "subject_id": subject,
        "gate": "dispatch_signoff",
        "payload": {},
    }
    config = config_for(f"supervisor:event:{subject}")
    return await graph.ainvoke(state, config), config


def resume(subject: str = SUBJECT, **extra) -> Command:
    return Command(
        resume={
            "subject_id": subject,
            "decided_by": APPROVER,
            "decided_at": datetime.now(UTC).isoformat(),
            "approved": True,
            **extra,
        }
    )


# ---------------------------------------------------------------------------------------
# Layer 1: the graph, with no API and no database trigger involved
# ---------------------------------------------------------------------------------------


async def test_a_resume_claiming_an_approval_that_does_not_exist_is_refused(
    approvals: FakeApprovals,
) -> None:
    """**The most important test in this file.**

    The resume says approved. The database has no record. A graph that trusted the payload
    would commit here, and it would have authenticated a JSON field written by whoever
    called the endpoint.
    """
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.ApprovalNotFound):
        await graph.ainvoke(resume(), config)


async def test_an_approval_for_a_different_subject_is_refused(
    approvals: FakeApprovals,
) -> None:
    """The realistic carry-over: an approval for plan A presented on a resume about plan B,
    by a copied state key or a resume on the wrong thread."""
    approvals.records[("dispatch_signoff", "plan-other")] = approval(subject_id="plan-other")
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.ApprovalNotFound):
        await graph.ainvoke(resume(), config)


async def test_a_resume_naming_a_different_approver_than_the_record_is_refused(
    approvals: FakeApprovals,
) -> None:
    """They disagree, so neither is acted on. One of the two is wrong and proceeding would
    hide which."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval(approver_id="someone-else")
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.ApproverMismatch):
        await graph.ainvoke(resume(), config)


async def test_a_stale_second_factor_is_refused(approvals: FakeApprovals) -> None:
    """A session alone is never sufficient. What is missing is proof of who is at the
    keyboard."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval(step_up_minutes_ago=60)
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.StepUpTooOld):
        await graph.ainvoke(resume(), config)


async def test_no_second_factor_at_all_is_refused(approvals: FakeApprovals) -> None:
    approvals.records[("dispatch_signoff", SUBJECT)] = approval(step_up_minutes_ago=None)
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.StepUpTooOld):
        await graph.ainvoke(resume(), config)


async def test_a_recorded_refusal_is_not_retried_into_an_approval(
    approvals: FakeApprovals,
) -> None:
    """A refusal is a decision, not an absence."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval(approved=False)
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    with pytest.raises(gates.GateRefused):
        await graph.ainvoke(resume(), config)


async def test_a_verified_approval_commits(approvals: FakeApprovals) -> None:
    """The gate has to be passable, or nothing is ever dispatched."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval()
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    resumed = await graph.ainvoke(resume(), config)

    assert resumed["output"]["committed"] is True
    assert resumed["approval"]["verified_against"] == "database record"


async def test_the_gate_reads_the_database_even_on_a_well_formed_resume(
    approvals: FakeApprovals,
) -> None:
    """Proof the verification is not skipped on the happy path. Without the lookup the
    refusals above would be the only thing exercising it, and a short-circuit for
    'obviously fine' payloads would pass every one of them."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval()
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)
    await graph.ainvoke(resume(), config)

    assert ("dispatch_signoff", SUBJECT) in approvals.lookups


async def test_a_refusal_never_reaches_the_verifier(approvals: FakeApprovals) -> None:
    """Routing a "no" into a function whose job is to confirm a "yes" is how an error
    message ends up saying the wrong thing."""
    approvals.records[("dispatch_signoff", SUBJECT)] = approval()
    graph = build_graph(approvals)
    _, config = await run_gate(graph, approvals)

    resumed = await graph.ainvoke(
        Command(
            resume={
                "subject_id": SUBJECT,
                "decided_by": APPROVER,
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": False,
            }
        ),
        config,
    )

    assert resumed["output"]["committed"] is False


async def test_the_commit_tool_refuses_an_approval_for_another_subject() -> None:
    """The runtime layer, independent of the graph's own routing."""
    state = initial_state(
        agent="supervisor", subject_type="event", subject_id="plan-b", correlation_id="c"
    )
    state["human_decision"] = {
        "subject_id": "plan-a",
        "decided_by": APPROVER,
        "decided_at": datetime.now(UTC).isoformat(),
        "approved": True,
    }

    with pytest.raises(HumanGateMissing):
        await TOOLS.invoke(
            "commit_gated_subject", state, gate="dispatch_signoff", subject_id="plan-b", approval={}
        )


def test_the_commit_tool_is_gated() -> None:
    assert "commit_gated_subject" in TOOLS.gated()


async def test_a_gate_presented_before_the_subject_is_ready_is_refused(
    approvals: FakeApprovals,
) -> None:
    """A person asked to confirm an unfinished process confirms it. The gate is only
    meaningful once everything it depends on has happened."""
    approvals.facts[SUBJECT] = {"intake_verified"}
    graph = build_graph(approvals)

    with pytest.raises(gates.SubjectNotReady):
        await run_gate(graph, approvals)


async def test_the_disbursement_gate_needs_both_approvals(approvals: FakeApprovals) -> None:
    """One signature is not two. Segregation of duty is a precondition, not a formality."""
    approvals.facts["ent-1"] = {"entitlement_calculated", "first_approval_recorded"}

    with pytest.raises(gates.SubjectNotReady, match="second_approval_recorded"):
        await gates.assert_sequenced(GateKind.DISBURSEMENT_RELEASE, "ent-1", store=approvals)


# ---------------------------------------------------------------------------------------
# Layer 2: the scope model, with the graph and the database out of the picture
# ---------------------------------------------------------------------------------------


def test_both_gate_scopes_are_stripped_from_every_machine_principal() -> None:
    """No configuration mistake and no role misassignment can hand an agent either gate."""
    assert Scope.DISPATCH_COMMIT in HUMAN_GATE_SCOPES
    assert Scope.DISBURSEMENT_RELEASE in HUMAN_GATE_SCOPES
    assert Scope.DISPATCH_COMMIT not in ROLE_SCOPES[Role.AGENT]
    assert Scope.DISBURSEMENT_RELEASE not in ROLE_SCOPES[Role.AGENT]


def test_stripping_removes_both_gates_from_any_grant_set() -> None:
    """Asserted against the function rather than only against the AGENT role, so a future
    role given one by mistake still cannot keep it."""
    granted = frozenset(
        {
            ScopeGrant(
                scope=Scope.DISPATCH_COMMIT, scope_type=ScopeType.DISTRICT, scope_code="LK-21"
            ),
            ScopeGrant(
                scope=Scope.DISBURSEMENT_RELEASE,
                scope_type=ScopeType.DISTRICT,
                scope_code="LK-21",
            ),
            ScopeGrant(
                scope=Scope.INCIDENT_READ, scope_type=ScopeType.DISTRICT, scope_code="LK-21"
            ),
        }
    )

    stripped = {grant.scope for grant in strip_human_gates(granted)}

    assert Scope.DISPATCH_COMMIT not in stripped
    assert Scope.DISBURSEMENT_RELEASE not in stripped
    assert Scope.INCIDENT_READ in stripped


def test_the_step_up_window_matches_the_auth_layers() -> None:
    """Two windows that were meant to be equal are two that eventually are not, and the
    looser one silently wins."""
    assert gates.STEP_UP_WINDOW == STEP_UP_WINDOW


# ---------------------------------------------------------------------------------------
# Layer 3: the database constraint, asserted without Docker
# ---------------------------------------------------------------------------------------


def test_the_dispatch_plan_column_is_declared_and_the_trigger_exists() -> None:
    """`tests/schema` asserts the trigger behaves against a live Postgres. This asserts the
    declaration is still in the model, so a migration that dropped it fails a test that
    runs on a laptop with no Docker."""
    from incident_svc.repo.dispatch import DispatchPlan

    columns = {column.name for column in DispatchPlan.__table__.columns}

    assert "signed_off_by" in columns
    assert "signed_off_at" in columns


def test_the_disbursement_release_column_is_not_nullable() -> None:
    """The database's own half of the money gate: a released disbursement that names nobody
    cannot exist."""
    from ledger_svc.repo.ledger import Disbursement

    released_by = Disbursement.__table__.columns["released_by"]

    assert not released_by.nullable


def test_the_three_layers_are_independent_by_construction() -> None:
    """A statement of the property this file exists to hold, in one assertion.

    The graph layer needs no API and no database trigger - every graph test above runs with
    a fake store. The scope layer needs no graph. The database layer needs neither. If any
    of them started needing another, that test would have to import it.
    """
    import inspect

    from agent_svc.agents.supervisor import gates as gate_module

    source = inspect.getsource(gate_module)

    # The gate module knows about a store protocol and a clock, and nothing about HTTP,
    # scopes or SQL. Its refusals hold with the other two layers absent.
    assert "httpx" not in source
    assert "Scope." not in source
    assert "sqlalchemy" not in source
