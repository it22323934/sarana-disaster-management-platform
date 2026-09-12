"""Resuming a dispatch plan's reasoning thread, and the token that carries the decision.

This closes the seam file 08 opened and file 12 could not fill. The property that makes it
worth testing separately from the gate: **incident-svc does not resume on its own
authority.**

agent-svc's resume endpoint is `require(Scope.AGENT_REVIEW, allow_machine=False)`. No
machine principal in the platform holds `agent:review`, deliberately - answering an agent's
question is a human act. So the resume forwards the token of the dispatcher who just
approved the plan, and agent-svc records the decision against them.

That is also the truthful attribution. A service credential here would produce an audit
trail saying incident-svc answered the question, which is false.
"""

from __future__ import annotations

import httpx
import pytest

from incident_svc.adapters.agent_runtime import (
    AgentRuntimeUnavailable,
    AgentThreadResumer,
    _as_resume_request,
)
from incident_svc.domain.dispatch_gate import NullResumer
from sarana_shared.auth.scopes import ROLE_SCOPES, Role, Scope

THREAD = "triage:dispatch_plan:plan-1"
APPROVE = {"decision": "approve", "approver_id": "user-7", "at": "2026-11-28T04:00:00+00:00"}
REJECT = {
    "decision": "reject",
    "approver_id": "user-7",
    "reason": "wrong_priority",
    "at": "2026-11-28T04:00:00+00:00",
}


def resumer_over(handler) -> AgentThreadResumer:
    """A resumer whose HTTP client is a stub, so no network is involved."""
    return AgentThreadResumer(
        "http://agent-svc:8005",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------------------
# The token is the point
# ---------------------------------------------------------------------------------------


async def test_the_dispatchers_token_is_forwarded() -> None:
    """Not a service credential. agent-svc refuses machines on `agent:review`, and the
    person who decided is who the decision should be recorded against."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"status": "COMPLETED"})

    await resumer_over(handler).resume(THREAD, APPROVE, token="dispatcher-token")

    assert seen["auth"] == "Bearer dispatcher-token"


async def test_a_resume_with_no_token_refuses_rather_than_inventing_a_credential() -> None:
    """The refusal that keeps the property honest.

    Falling back to a service credential here would route around `allow_machine=False`,
    which is the whole reason that flag is set.
    """

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made without a token")

    with pytest.raises(AgentRuntimeUnavailable, match="No caller token"):
        await resumer_over(handler).resume(THREAD, APPROVE, token=None)


def test_no_machine_principal_holds_the_scope_the_resume_needs() -> None:
    """The reason the token is forwarded at all, asserted rather than assumed."""
    assert Scope.AGENT_REVIEW not in ROLE_SCOPES[Role.AGENT]
    assert Scope.AGENT_REVIEW not in ROLE_SCOPES[Role.SERVICE]


def test_the_roles_that_decide_a_dispatch_can_answer_the_agent() -> None:
    """If this broke, every approval would fail with a 403 from agent-svc - and the plan
    would not be released, because `approve` treats a failed resume as fatal."""
    assert Scope.AGENT_REVIEW in ROLE_SCOPES[Role.DISPATCHER]
    assert Scope.AGENT_REVIEW in ROLE_SCOPES[Role.DMC_OPERATOR]


# ---------------------------------------------------------------------------------------
# Translating between two vocabularies
# ---------------------------------------------------------------------------------------


def test_an_approval_becomes_approved_true() -> None:
    """The gate says `decision: approve` because that is what a plan row records; agent-svc
    says `approved: bool` because that is what every interrupt asks."""
    assert _as_resume_request(APPROVE)["approved"] is True


def test_a_rejection_becomes_approved_false_and_keeps_its_reason() -> None:
    body = _as_resume_request(REJECT)

    assert body["approved"] is False
    assert body["reason"] == "wrong_priority"


def test_the_approver_is_identified_by_id_not_by_name() -> None:
    """The decision goes into a checkpoint, and a checkpoint carries ids, never people."""
    assert _as_resume_request(APPROVE)["decided_by"] == "user-7"


def test_anything_else_the_decision_carries_is_passed_through() -> None:
    """So a dispatcher who reduces a responder count while approving does not lose it."""
    body = _as_resume_request({**APPROVE, "responder_ids": ["r1"]})

    assert body["payload"] == {"responder_ids": ["r1"]}


# ---------------------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------------------


async def test_an_unreachable_agent_svc_raises() -> None:
    """The gate turns this into `GraphResumeFailed` on approve, and the plan is not
    released: a plan whose graph never resumed has not completed the reasoning that
    produced it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AgentRuntimeUnavailable, match="unreachable"):
        await resumer_over(handler).resume(THREAD, APPROVE, token="t")


async def test_a_refusal_from_agent_svc_raises_rather_than_being_swallowed() -> None:
    """403 is what a caller without `agent:review` gets. A dispatcher whose token cannot
    answer the agent's question needs to know, and so does whoever configured the role."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    with pytest.raises(AgentRuntimeUnavailable, match="403"):
        await resumer_over(handler).resume(THREAD, APPROVE, token="t")


async def test_a_successful_resume_reports_that_the_graph_moved() -> None:
    """`graph_resumed` is what the approve response shows a dispatcher. With `NullResumer`
    it is false, and it must become true only when a graph genuinely ran."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "COMPLETED", "output": {"released": True}})

    state = await resumer_over(handler).resume(THREAD, APPROVE, token="t")

    assert state["graph_resumed"] is True
    assert state["status"] == "COMPLETED"


async def test_the_null_resumer_still_reports_that_no_graph_ran() -> None:
    """A deployment with the agents switched off has plans with no thread at all. The gate
    must stay usable, and nothing may mistake this for a completed agent decision."""
    state = await NullResumer().resume(THREAD, APPROVE, token="t")

    assert state["graph_resumed"] is False


async def test_the_resume_targets_the_thread_it_was_given() -> None:
    """A resume on the wrong thread would answer somebody else's question."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "COMPLETED"})

    await resumer_over(handler).resume(THREAD, APPROVE, token="t")

    assert seen["url"].endswith(f"/api/v1/agents/threads/{THREAD}/resume")
