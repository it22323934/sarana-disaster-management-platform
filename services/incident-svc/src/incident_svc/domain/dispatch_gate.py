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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

# The step-up window. A session alone is never sufficient: the code must be presented with
# this request, so approving is a deliberate act rather than a consequence of being logged
# in when a plan happened to arrive.
STEP_UP_WINDOW: Final = timedelta(minutes=5)


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


class TOTPVerifier(Protocol):
    """Verifies a step-up code for one subject."""

    def verify(self, subject_id: str, code: str) -> bool: ...


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


def assert_step_up(verifier: TOTPVerifier, subject_id: str, code: str | None) -> None:
    """Require a TOTP presented with this request.

    Raises:
        StepUpFailed: mapped to 401, never 403. The caller may well hold the scope; what
            is missing is the second factor, and saying so is the difference between "you
            cannot do this" and "prove it is you".
    """
    if not code:
        raise StepUpFailed(
            "Releasing a dispatch requires a TOTP code presented with the request. "
            "An authenticated session is not sufficient."
        )
    if not verifier.verify(subject_id, code):
        raise StepUpFailed("That verification code is not valid.")


async def approve(
    plan: dict[str, Any],
    *,
    approver_id: UUID,
    totp_code: str | None,
    verifier: TOTPVerifier,
    resumer: ThreadResumer,
) -> GateDecision:
    """Run the gate for an approval.

    The caller is responsible for having checked `Scope.DISPATCH_COMMIT` for the plan's
    district before reaching here - that check belongs with the endpoint, which knows how
    to resolve the area. Everything after it belongs here.
    """
    assert_undecided(plan)
    assert_step_up(verifier, str(approver_id), totp_code)

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
        except Exception as error:  # noqa: BLE001 - any resume failure refuses the release
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
    approver_id: UUID,
    reason: RejectionReason,
    note: str | None,
    totp_code: str | None,
    verifier: TOTPVerifier,
    resumer: ThreadResumer,
) -> GateDecision:
    """Run the gate for a rejection.

    Rejection is step-up gated too. It is not the dangerous direction, but an attacker who
    can reject every plan can stop a response as effectively as one who can release a bad
    one, and the asymmetry would be the obvious thing to exploit.
    """
    assert_undecided(plan)
    assert_step_up(verifier, str(approver_id), totp_code)

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
