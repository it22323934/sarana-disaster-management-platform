"""The dispatch human gate.

One of the two mandatory gates. Committing a dispatch sends people towards a hazard, and
no model and no configuration may do it alone.

The order below is the order from the build brief, and it is deliberate: scope before
TOTP, so an unauthorised caller is refused without being told whether their code was
right; TOTP before any state change, so a failed second factor leaves nothing behind.

**There is no path to RELEASED that does not pass through `approve()`.** No flag, no
environment variable, no seed script. Three independent things enforce that, and they fail
independently:

  1. This function, which is the only writer of `signed_off_by`.
  2. `Scope.DISPATCH_COMMIT`, which `strip_human_gates()` removes from every machine
     principal at mint time, so no agent can hold it however it is configured.
  3. `incident.enforce_dispatch_human_gate()`, a database trigger that rejects RELEASED
     without a recorded sign-off regardless of which application wrote the row.

The build brief names `Scope.DISPATCH_APPROVE`; the scope that exists and is stripped from
machine principals is `DISPATCH_COMMIT`, which is the one used here.

**Where the second factor is checked.** The brief says to verify a TOTP presented in this
request. The platform verifies it one step earlier and this service does not see the code
at all: core-api owns the MFA secrets, its step-up endpoint verifies the code and stamps
`step_up_at` into a fresh token, and the gate requires that stamp to be under five minutes
old. The guarantee the brief asks for is the one that holds - a session alone is never
sufficient, and the person must have proved possession of their factor within the window.

Verifying the code here instead would mean incident-svc holding or fetching every
dispatcher's MFA secret, which spreads the most sensitive credential in the system across
services to re-derive a fact core-api already established.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import structlog

from sarana_shared.auth.principal import STEP_UP_WINDOW, Principal
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

# The window comes from the auth layer rather than being restated here. Two constants that
# were meant to be equal are two constants that eventually are not, and the one that would
# silently win is the looser.


class RejectionReason(StrEnum):
    """Why a dispatcher turned a plan down.

    A fixed taxonomy, because rejections are the highest-value training signal the system
    produces and free text cannot be aggregated. `OTHER` still requires a note.
    """

    WRONG_PRIORITY = "wrong_priority"
    DUPLICATE = "duplicate"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    ALREADY_HANDLED = "already_handled"
    BAD_LOCATION = "bad_location"
    OTHER = "other"


class GateRefused(Exception):
    """The plan was not released, and why."""


class StepUpFailed(GateRefused):
    """No valid TOTP was presented with the request."""


class AlreadyDecided(GateRefused):
    """The plan already carries a decision.

    Approving twice is a double-click, not a second dispatch. It is refused rather than
    treated as idempotent success, because the second caller may be a different person
    who needs to know the decision was already made and by whom.
    """

    def __init__(self, plan_id: UUID, status: str, signed_off_by: UUID | None) -> None:
        super().__init__(
            f"dispatch plan {plan_id} is already {status}"
            + (f", signed off by {signed_off_by}" if signed_off_by else "")
        )
        self.plan_id = plan_id
        self.status = status
        self.signed_off_by = signed_off_by


class GraphResumeFailed(GateRefused):
    """The plan's reasoning thread could not be resumed.

    Refusing is the safe direction. A plan whose graph never resumed has not completed the
    reasoning that produced it, and releasing it anyway would mean dispatching on a partial
    decision while the audit trail claims a complete one.
    """


class ThreadResumer(Protocol):
    """Resumes a paused LangGraph thread past its interrupt.

    The agent runtime is build file 12 and does not exist yet. This protocol is the seam:
    the gate calls it, `NullResumer` stands in until the runtime lands, and none of the
    safety properties above depend on which implementation is present.
    """

    async def resume(self, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Resume `thread_id`, returning the graph's state after the interrupt."""
        ...


class NullResumer:
    """Stands in until the LangGraph runtime exists.

    Accepts the resume and records that no graph was involved. It deliberately does not
    fail closed: a plan proposed without an agent - which is what happens in degraded mode
    - has no thread to resume, and refusing those would mean the gate could not be used at
    all with the agents switched off.

    The response says `graph_resumed: false` so nothing downstream can mistake this for a
    completed agent decision.
    """

    async def resume(self, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _log.info(
            "dispatch_graph_resume_skipped",
            thread_id=thread_id,
            reason="no agent runtime configured",
            decision=payload.get("decision"),
        )
        return {"graph_resumed": False, "thread_id": thread_id}


@dataclass(frozen=True, slots=True)
class GateDecision:
    """What the gate decided, and everything the audit entry needs."""

    plan_id: UUID
    decision: str
    approver_id: UUID
    at: Any
    graph_resumed: bool
    reason: RejectionReason | None = None
    note: str | None = None

    def as_audit_payload(self) -> dict[str, Any]:
        return {
            "plan_id": str(self.plan_id),
            "decision": self.decision,
            "approver_id": str(self.approver_id),
            "at": self.at.isoformat(),
            "graph_resumed": self.graph_resumed,
            "reason": self.reason.value if self.reason else None,
            "note": self.note,
        }


def assert_undecided(plan: dict[str, Any]) -> None:
    """Refuse a plan that already carries a decision.

    Raises:
        AlreadyDecided: mapped to 409.
    """
    status = str(plan["status"])
    if status in {"APPROVED", "RELEASED", "COMPLETED", "REJECTED"}:
        raise AlreadyDecided(plan["id"], status, plan.get("signed_off_by"))


def assert_step_up(principal: Principal) -> None:
    """Require a second factor verified inside the step-up window.

    Checked here as well as by the `require(...)` dependency. That is deliberate
    duplication: this function is the only writer of a sign-off, and a safety property
    that lives solely in a decorator is one refactor away from being lost.

    Raises:
        StepUpFailed: mapped to 401, never 403. The caller may well hold the scope; what
            is missing is proof of who is at the keyboard, and saying so is the difference
            between "you cannot do this" and "prove it is you".
    """
    if not principal.has_fresh_step_up():
        raise StepUpFailed(
            "Releasing a dispatch requires a second factor verified within the last "
            f"{int(STEP_UP_WINDOW.total_seconds() // 60)} minutes. Step up at "
            "/api/v1/auth/step-up and retry; an authenticated session is not sufficient."
        )


async def approve(
    plan: dict[str, Any],
    *,
    principal: Principal,
    resumer: ThreadResumer,
) -> GateDecision:
    """Run the gate for an approval.

    The caller is responsible for having checked `Scope.DISPATCH_COMMIT` for the plan's
    district before reaching here - that check belongs with the endpoint, which knows how
    to resolve the area. Everything after it belongs here.
    """
    assert_undecided(plan)
    assert_step_up(principal)
    approver_id = UUID(principal.subject_id)

    at = utc_now()
    thread_id = plan.get("langgraph_thread_id")

    graph_resumed = False
    if thread_id:
        try:
            state = await resumer.resume(
                str(thread_id),
                {
                    "decision": "approve",
                    "approver_id": str(approver_id),
                    "at": at.isoformat(),
                },
            )
        except Exception as error:
            raise GraphResumeFailed(
                f"the reasoning thread for plan {plan['id']} could not be resumed: {error}. "
                "The plan has not been released."
            ) from error
        graph_resumed = bool(state.get("graph_resumed", True))

    _log.info(
        "dispatch_plan_approved",
        plan_id=str(plan["id"]),
        approver_id=str(approver_id),
        graph_resumed=graph_resumed,
    )
    return GateDecision(
        plan_id=plan["id"],
        decision="approve",
        approver_id=approver_id,
        at=at,
        graph_resumed=graph_resumed,
    )


async def reject(
    plan: dict[str, Any],
    *,
    principal: Principal,
    reason: RejectionReason,
    note: str | None,
    resumer: ThreadResumer,
) -> GateDecision:
    """Run the gate for a rejection.

    Rejection is step-up gated too. It is not the dangerous direction, but an attacker who
    can reject every plan can stop a response as effectively as one who can release a bad
    one, and the asymmetry would be the obvious thing to exploit.
    """
    assert_undecided(plan)
    assert_step_up(principal)
    approver_id = UUID(principal.subject_id)

    if reason is RejectionReason.OTHER and not (note and note.strip()):
        raise GateRefused(
            "a rejection reason of 'other' must carry a note; rejections are the "
            "training signal the Learn loop runs on, and an uncategorised one teaches "
            "nothing"
        )

    at = utc_now()
    thread_id = plan.get("langgraph_thread_id")
    graph_resumed = False
    if thread_id:
        try:
            state = await resumer.resume(
                str(thread_id),
                {
                    "decision": "reject",
                    "approver_id": str(approver_id),
                    "reason": reason.value,
                    "at": at.isoformat(),
                },
            )
            graph_resumed = bool(state.get("graph_resumed", True))
        except Exception:  # noqa: BLE001 - a rejection stands whatever the graph does
            # Deliberately different from approve(). A rejection that cannot reach the
            # graph is still a rejection: refusing it would leave a plan the dispatcher
            # has declined sitting in the queue looking live.
            _log.warning("dispatch_graph_resume_failed_on_reject", plan_id=str(plan["id"]))

    _log.info(
        "dispatch_plan_rejected",
        plan_id=str(plan["id"]),
        approver_id=str(approver_id),
        reason=reason.value,
    )
    return GateDecision(
        plan_id=plan["id"],
        decision="reject",
        approver_id=approver_id,
        at=at,
        graph_resumed=graph_resumed,
        reason=reason,
        note=note,
    )
