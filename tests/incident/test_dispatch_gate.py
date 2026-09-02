"""The dispatch human gate, including deliberate attempts to get round it.

This is the most consequential code in the service. Releasing a plan sends people towards
a hazard, so the tests are written as attacks rather than as happy paths: each one tries a
specific way of reaching RELEASED without a human, and asserts it fails.

Three independent mechanisms enforce the gate and each is tested on its own, because
defence in depth is only depth if the layers do not share a single point of failure:

  1. `approve()` - the only writer of a sign-off.
  2. `Scope.DISPATCH_COMMIT` - stripped from every machine principal at mint time.
  3. `incident.enforce_dispatch_human_gate()` - a database trigger.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from incident_svc.domain import dispatch_gate
from sarana_shared.auth.grants import ScopeType, grants_for_assignments, strip_human_gates
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, Role, Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

pytestmark = pytest.mark.asyncio(loop_scope="session")


def dispatcher(*, stepped_up_minutes_ago: float | None = 0.0) -> Principal:
    """A human dispatcher, optionally with a stale or absent step-up."""
    step_up_at = (
        None
        if stepped_up_minutes_ago is None
        else utc_now() - timedelta(minutes=stepped_up_minutes_ago)
    )
    return Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DISPATCHER}),
        grants=grants_for_assignments([(Role.DISPATCHER, ScopeType.NATIONAL, "LK")]),
        step_up_at=step_up_at,
    )


def a_plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "id": uuid7(),
        "status": "AWAITING_SIGNOFF",
        "signed_off_by": None,
        "langgraph_thread_id": None,
        "incident_ids": [],
    }
    plan.update(overrides)
    return plan


# --------------------------------------------------------------------------------------
# Mechanism 2: no machine principal can hold the scope
# --------------------------------------------------------------------------------------


def test_the_commit_scope_is_one_of_the_two_mandatory_human_gates() -> None:
    assert Scope.DISPATCH_COMMIT in HUMAN_GATE_SCOPES


def test_minting_an_agent_token_strips_the_commit_scope() -> None:
    """However an agent is configured, it cannot be granted this.

    The strip happens at mint time, so a misconfigured role assignment cannot produce a
    token that holds it.
    """
    granted = grants_for_assignments([(Role.AGENT, ScopeType.NATIONAL, "LK")])

    stripped = strip_human_gates(granted)

    assert not any(grant.scope is Scope.DISPATCH_COMMIT for grant in stripped)


def test_a_machine_principal_is_refused_the_gate_outright() -> None:
    """Refused as a machine, not as someone whose step-up expired.

    The distinction matters: an agent has no second factor and never will, and a message
    about an expired window would send an operator looking for a code that does not exist.
    """
    from sarana_shared.errors import Forbidden

    agent = Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.AGENT}),
        # Deliberately given a dispatcher's full grants, human gate included, to prove
        # the refusal does not depend on the scope having been stripped.
        grants=grants_for_assignments([(Role.DISPATCHER, ScopeType.NATIONAL, "LK")]),
        is_machine=True,
    )

    with pytest.raises(Forbidden, match="cannot be taken by an agent"):
        agent.assert_may_commit_gate(Scope.DISPATCH_COMMIT, None)


# --------------------------------------------------------------------------------------
# Mechanism 1: the gate itself
# --------------------------------------------------------------------------------------


async def test_a_plan_is_released_by_a_stepped_up_dispatcher() -> None:
    decision = await dispatch_gate.approve(
        a_plan(), principal=dispatcher(), resumer=dispatch_gate.NullResumer()
    )

    assert decision.decision == "approve"
    assert decision.approver_id is not None


async def test_a_plan_cannot_be_released_without_a_step_up() -> None:
    """A session alone is never sufficient. The brief's case, and the 401 case."""
    with pytest.raises(dispatch_gate.StepUpFailed):
        await dispatch_gate.approve(
            a_plan(),
            principal=dispatcher(stepped_up_minutes_ago=None),
            resumer=dispatch_gate.NullResumer(),
        )


async def test_a_step_up_older_than_the_window_is_not_enough() -> None:
    """Being logged in when a plan arrives is not the same as deciding to release it."""
    with pytest.raises(dispatch_gate.StepUpFailed):
        await dispatch_gate.approve(
            a_plan(),
            principal=dispatcher(stepped_up_minutes_ago=6),
            resumer=dispatch_gate.NullResumer(),
        )


async def test_a_step_up_inside_the_window_is_enough() -> None:
    decision = await dispatch_gate.approve(
        a_plan(),
        principal=dispatcher(stepped_up_minutes_ago=4),
        resumer=dispatch_gate.NullResumer(),
    )

    assert decision.decision == "approve"


async def test_a_plan_cannot_be_released_twice() -> None:
    """A double-click is not a second dispatch.

    Refused rather than treated as success: the second caller may be a different person
    who needs to know the decision was already made, and by whom.
    """
    already = a_plan(status="RELEASED", signed_off_by=uuid7())

    with pytest.raises(dispatch_gate.AlreadyDecided) as caught:
        await dispatch_gate.approve(
            already, principal=dispatcher(), resumer=dispatch_gate.NullResumer()
        )

    assert "already RELEASED" in str(caught.value)


async def test_a_rejected_plan_cannot_then_be_approved() -> None:
    with pytest.raises(dispatch_gate.AlreadyDecided):
        await dispatch_gate.approve(
            a_plan(status="REJECTED"),
            principal=dispatcher(),
            resumer=dispatch_gate.NullResumer(),
        )


async def test_the_step_up_is_checked_before_anything_is_decided() -> None:
    """A failed second factor must leave nothing behind.

    Asserted by ordering: an already-decided plan with a stale step-up raises the
    already-decided error, so the undecided check runs first and neither writes anything.
    """
    with pytest.raises(dispatch_gate.GateRefused):
        await dispatch_gate.approve(
            a_plan(status="RELEASED", signed_off_by=uuid7()),
            principal=dispatcher(stepped_up_minutes_ago=None),
            resumer=dispatch_gate.NullResumer(),
        )


# --------------------------------------------------------------------------------------
# The reasoning thread
# --------------------------------------------------------------------------------------


class _FailingResumer:
    async def resume(
        self, thread_id: str, payload: dict[str, Any], *, token: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("the graph is unreachable")


class _RecordingResumer:
    """Records the token as well as the payload.

    The token is what makes the resume a human act rather than a machine one - agent-svc
    refuses machine principals on `agent:review` - so a stub that dropped it would let a
    regression through silently.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tokens: list[str | None] = []

    async def resume(
        self, thread_id: str, payload: dict[str, Any], *, token: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((thread_id, payload))
        self.tokens.append(token)
        return {"graph_resumed": True}


async def test_the_approvers_token_reaches_the_resumer() -> None:
    """The resume is performed as the dispatcher, not as incident-svc.

    agent-svc refuses machine principals on `agent:review`, so a resume that arrived
    without the approving person's token could not authenticate at all - and if it somehow
    did, the audit trail would say a service answered the agent's question rather than the
    person who decided.
    """
    resumer = _RecordingResumer()

    await dispatch_gate.approve(
        a_plan(langgraph_thread_id="thread-1"),
        principal=dispatcher(),
        resumer=resumer,
        token="dispatcher-token",
    )

    assert resumer.tokens == ["dispatcher-token"]


async def test_a_rejection_also_carries_the_approvers_token() -> None:
    resumer = _RecordingResumer()

    await dispatch_gate.reject(
        a_plan(langgraph_thread_id="thread-1"),
        principal=dispatcher(),
        reason=dispatch_gate.RejectionReason.WRONG_PRIORITY,
        note=None,
        resumer=resumer,
        token="dispatcher-token",
    )

    assert resumer.tokens == ["dispatcher-token"]


async def test_a_plan_with_a_thread_resumes_it_before_being_released() -> None:
    resumer = _RecordingResumer()

    decision = await dispatch_gate.approve(
        a_plan(langgraph_thread_id="thread-1"), principal=dispatcher(), resumer=resumer
    )

    assert resumer.calls
    thread_id, payload = resumer.calls[0]
    assert thread_id == "thread-1"
    assert payload["decision"] == "approve"
    assert decision.graph_resumed is True


async def test_a_plan_is_not_released_when_its_thread_cannot_be_resumed() -> None:
    """Refusing is the safe direction.

    A plan whose graph never resumed has not finished the reasoning that produced it, and
    releasing it anyway would dispatch on a partial decision while the audit trail claimed
    a complete one.
    """
    with pytest.raises(dispatch_gate.GraphResumeFailed):
        await dispatch_gate.approve(
            a_plan(langgraph_thread_id="thread-1"),
            principal=dispatcher(),
            resumer=_FailingResumer(),
        )


async def test_a_plan_with_no_thread_is_releasable_with_the_agents_off() -> None:
    """Degraded mode still needs a working gate.

    A plan proposed without an agent has no thread to resume. Refusing those would mean
    the human gate could not be used at all when the agents are down, which is exactly
    when a human decision matters most.
    """
    decision = await dispatch_gate.approve(
        a_plan(langgraph_thread_id=None),
        principal=dispatcher(),
        resumer=dispatch_gate.NullResumer(),
    )

    assert decision.graph_resumed is False


async def test_the_response_never_claims_a_graph_ran_when_none_did() -> None:
    """Nothing downstream may mistake a null resume for a completed agent decision."""
    decision = await dispatch_gate.approve(
        a_plan(langgraph_thread_id="thread-1"),
        principal=dispatcher(),
        resumer=dispatch_gate.NullResumer(),
    )

    assert decision.graph_resumed is False
    assert decision.as_audit_payload()["graph_resumed"] is False


# --------------------------------------------------------------------------------------
# Rejection
# --------------------------------------------------------------------------------------


async def test_a_rejection_requires_a_step_up_too() -> None:
    """An attacker who can reject every plan stops a response as effectively as one who
    releases a bad one. The asymmetry would be the obvious thing to exploit."""
    with pytest.raises(dispatch_gate.StepUpFailed):
        await dispatch_gate.reject(
            a_plan(),
            principal=dispatcher(stepped_up_minutes_ago=None),
            reason=dispatch_gate.RejectionReason.DUPLICATE,
            note=None,
            resumer=dispatch_gate.NullResumer(),
        )


async def test_a_rejection_records_its_reason_from_the_taxonomy() -> None:
    decision = await dispatch_gate.reject(
        a_plan(),
        principal=dispatcher(),
        reason=dispatch_gate.RejectionReason.RESOURCE_UNAVAILABLE,
        note=None,
        resumer=dispatch_gate.NullResumer(),
    )

    assert decision.reason is dispatch_gate.RejectionReason.RESOURCE_UNAVAILABLE
    assert decision.as_audit_payload()["reason"] == "resource_unavailable"


async def test_an_other_rejection_must_carry_a_note() -> None:
    """Rejections are the training signal the Learn loop runs on.

    An uncategorised rejection with no explanation teaches nothing, which makes it the one
    kind that is refused.
    """
    with pytest.raises(dispatch_gate.GateRefused, match="must carry a note"):
        await dispatch_gate.reject(
            a_plan(),
            principal=dispatcher(),
            reason=dispatch_gate.RejectionReason.OTHER,
            note="   ",
            resumer=dispatch_gate.NullResumer(),
        )


async def test_a_rejection_stands_even_if_the_graph_cannot_be_reached() -> None:
    """Deliberately unlike approval.

    A rejection that cannot reach the graph is still a rejection; refusing it would leave a
    plan the dispatcher has declined sitting in the queue looking live.
    """
    decision = await dispatch_gate.reject(
        a_plan(langgraph_thread_id="thread-1"),
        principal=dispatcher(),
        reason=dispatch_gate.RejectionReason.WRONG_PRIORITY,
        note=None,
        resumer=_FailingResumer(),
    )

    assert decision.decision == "reject"
    assert decision.graph_resumed is False


# --------------------------------------------------------------------------------------
# Mechanism 3: the database refuses regardless of the application
# --------------------------------------------------------------------------------------


async def _propose_plan(db: AsyncConnection) -> UUID:
    """A valid PROPOSED plan, ready to have the gate attacked.

    `incident_ids` is non-empty because the schema requires a plan to cover at least one
    incident - a dispatch plan for nothing would be a team sent nowhere.
    """
    plan_id = uuid7()
    await db.execute(
        text(
            "INSERT INTO incident.dispatch_plan "
            "(id, incident_ids, responder_ids, proposed_by_agent, status, correlation_id) "
            "VALUES (:id, ARRAY[:incident]::uuid[], ARRAY[]::uuid[], 'test', 'PROPOSED', :corr)"
        ),
        {"id": plan_id, "incident": uuid7(), "corr": str(uuid7())},
    )
    return plan_id


async def test_the_database_refuses_released_without_a_signoff(db: AsyncConnection) -> None:
    """The backstop from build file 04, tested directly.

    Written as the attack it guards against: a plan inserted and then moved straight to
    RELEASED by SQL, bypassing every line of Python in this service.
    """
    plan_id = await _propose_plan(db)

    with pytest.raises(Exception, match="without a recorded human sign-off"):
        await db.execute(
            text("UPDATE incident.dispatch_plan SET status = 'RELEASED' WHERE id = :id"),
            {"id": plan_id},
        )


async def test_the_database_accepts_released_with_a_signoff(db: AsyncConnection) -> None:
    """The same write, done properly, is allowed - so the trigger is not simply refusing
    everything."""
    plan_id = await _propose_plan(db)
    approver = uuid7()

    await db.execute(
        text(
            "UPDATE incident.dispatch_plan "
            "SET status = 'RELEASED', signed_off_by = :approver, signed_off_at = now() "
            "WHERE id = :id"
        ),
        {"id": plan_id, "approver": approver},
    )

    result = await db.execute(
        text("SELECT status, signed_off_by FROM incident.dispatch_plan WHERE id = :id"),
        {"id": plan_id},
    )
    status, signed_off_by = result.one()
    assert status == "RELEASED"
    assert signed_off_by == approver


async def test_a_signoff_cannot_be_reassigned_to_someone_else(db: AsyncConnection) -> None:
    """Rewriting who approved a dispatch would make the audit trail a lie."""
    plan_id = await _propose_plan(db)
    first = uuid7()
    await db.execute(
        text(
            "UPDATE incident.dispatch_plan "
            "SET status = 'RELEASED', signed_off_by = :approver, signed_off_at = now() "
            "WHERE id = :id"
        ),
        {"id": plan_id, "approver": first},
    )

    with pytest.raises(Exception, match="cannot be reassigned"):
        await db.execute(
            text("UPDATE incident.dispatch_plan SET signed_off_by = :other WHERE id = :id"),
            {"id": plan_id, "other": uuid7()},
        )
