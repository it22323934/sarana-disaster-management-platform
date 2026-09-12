"""The disbursement human gate.

The second of the two mandatory gates. Releasing money is irreversible in practice - a
payment sent to the wrong household is not coming back - so every check here is a refusal
by default.

The order is from build file 10 and it is load-bearing. Scope before step-up, so an
unauthorised caller is refused without learning whether their second factor would have
worked. Segregation before the amount, so the cheapest structural check runs before the
arithmetic. Everything before the write, so a refused release leaves nothing behind.

**There is no bulk release.** Not "not yet implemented" - deliberately absent. A bulk
endpoint is one mis-selected filter away from paying an entire district twice, and the one
place a human gate must not be is behind a checkbox that says "apply to all". If it is ever
added it releases one at a time under one step-up, with an explicit per-item list and a
hard cap.

**There is no amount field.** The amount comes from the entitlement, which came from the
calculation, which came from the pinned schedule. A releaser who could type a number would
make the entire trace decorative.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from ledger_svc.domain.approval import DEFAULT_DISTRICT_THRESHOLD_CENTS
from sarana_shared.auth.principal import STEP_UP_WINDOW, Principal
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)


class ReleaseRefused(Exception):
    """The money was not released, and why."""


class StepUpRequired(ReleaseRefused):
    """No second factor was verified recently enough.

    Mapped to 401, not 403: the caller may well hold the scope. What is missing is proof
    of who is at the keyboard.
    """


class SegregationViolated(ReleaseRefused):
    """The releaser is too close to the decision.

    Its own type because this is the check that catches the fraud the whole approval chain
    exists to prevent - one person assessing, approving and paying.
    """


class ApprovalsIncomplete(ReleaseRefused):
    """A required approval is missing, refused, or superseded."""


class GrievanceOpen(ReleaseRefused):
    """A household has disputed this entitlement and nobody has dispositioned it.

    Only blocks *this* release. An open grievance elsewhere in the district stops nothing:
    a complaints process that halts unrelated aid teaches everyone not to complain.
    """


class AlreadyReleased(ReleaseRefused):
    """This entitlement has already been paid.

    Refused rather than treated as idempotent success. A second caller may be a different
    officer who needs to know it is done, and by whom.
    """


class ApprovalLevel(StrEnum):
    DS = "DS"
    DISTRICT = "DISTRICT"


# Above this, a district-level approval is required as well as the DS one. Below it, the
# DS approval alone is enough - the second pair of eyes costs more than it saves on a
# household goods payment, and slowing every small release delays the people least able to
# wait.
#
# Imported from `domain.approval` rather than restated. The two modules held different
# numbers until this was noticed, which put entitlements between them in a state where the
# approval flow reported them ready and the release then refused them for a signature
# nobody had been asked for.
DISTRICT_APPROVAL_THRESHOLD_CENTS: Final = DEFAULT_DISTRICT_THRESHOLD_CENTS


@dataclass(frozen=True, slots=True)
class Approval:
    """One recorded approval on an entitlement."""

    level: ApprovalLevel
    approver_id: UUID
    decision: str
    superseded: bool = False

    @property
    def is_valid(self) -> bool:
        return self.decision == "APPROVED" and not self.superseded


@dataclass(frozen=True, slots=True)
class ReleaseContext:
    """Everything the gate needs to decide, gathered before it is called.

    A single object so the checks below are pure and exhaustively testable - the gate
    never reaches back into the database mid-decision, which is what would make the order
    of its checks unverifiable.
    """

    entitlement_id: UUID
    amount_lkr_cents: int
    district_code: str
    assessor_id: UUID
    approvals: list[Approval]
    open_grievance_ids: list[UUID]
    already_released: bool = False

    @property
    def requires_district_approval(self) -> bool:
        return self.amount_lkr_cents > DISTRICT_APPROVAL_THRESHOLD_CENTS


class PaymentRail(Protocol):
    """A way of actually moving the money.

    Every implementation in Phase 1 is a mock. The interface is real so the gate above it
    is exercised properly; the transport is not, and the payment reference says so.
    """

    name: str

    async def send(self, *, amount_lkr_cents: int, reference: str) -> str:
        """Move the money and return the rail's own reference."""
        ...


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """What the gate approved, and everything the ledger entry needs."""

    entitlement_id: UUID
    amount_lkr_cents: int
    released_by: UUID
    at: Any
    payment_ref: str | None = None
    graph_resumed: bool = False

    def as_audit_payload(self) -> dict[str, Any]:
        return {
            "entitlement_id": str(self.entitlement_id),
            "amount_lkr_cents": self.amount_lkr_cents,
            "released_by": str(self.released_by),
            "at": self.at.isoformat(),
            "payment_ref": self.payment_ref,
            "graph_resumed": self.graph_resumed,
        }


def assert_not_released(context: ReleaseContext) -> None:
    """Refuse a second release of the same entitlement."""
    if context.already_released:
        raise AlreadyReleased(f"entitlement {context.entitlement_id} has already been disbursed")


def assert_step_up(principal: Principal) -> None:
    """Require a second factor verified inside the step-up window.

    Checked here as well as by the `require(...)` dependency. Deliberate duplication: this
    module is the only place a release is authorised, and a safety property that lives
    solely in a decorator is one refactor away from being lost.
    """
    if not principal.has_fresh_step_up():
        raise StepUpRequired(
            "Releasing money requires a second factor verified within the last "
            f"{int(STEP_UP_WINDOW.total_seconds() // 60)} minutes. Step up and retry; an "
            "authenticated session is not sufficient."
        )


def assert_segregation(context: ReleaseContext, releaser_id: UUID) -> None:
    """The releaser must not be the assessor or any approver.

    This is the check that catches the fraud the approval chain exists to prevent. One
    person who can assess damage, approve the entitlement and release the money needs no
    accomplice and leaves no disagreement in the record.
    """
    if releaser_id == context.assessor_id:
        raise SegregationViolated(
            "the officer who assessed this damage may not also release the payment"
        )

    for approval in context.approvals:
        if approval.approver_id == releaser_id and approval.is_valid:
            raise SegregationViolated(
                f"the {approval.level.value} approver on this entitlement may not also "
                "release the payment"
            )


def assert_approvals_complete(context: ReleaseContext) -> None:
    """Every required approval present, valid, and not superseded.

    A superseded approval is one attached to a recalculated entitlement. It approved a
    different number, and treating it as current would release money nobody agreed to.
    """
    valid = [approval for approval in context.approvals if approval.is_valid]
    levels = {approval.level for approval in valid}

    if ApprovalLevel.DS not in levels:
        superseded = any(
            approval.level is ApprovalLevel.DS and approval.superseded
            for approval in context.approvals
        )
        raise ApprovalsIncomplete(
            "a DS approval is required and "
            + (
                "the one on record was superseded by a recalculation"
                if superseded
                else "none is recorded"
            )
        )

    if context.requires_district_approval and ApprovalLevel.DISTRICT not in levels:
        raise ApprovalsIncomplete(
            f"this entitlement is {context.amount_lkr_cents / 100:,.2f}, above the "
            f"{DISTRICT_APPROVAL_THRESHOLD_CENTS / 100:,.2f} threshold, so a district "
            "approval is required as well as the DS one"
        )


def assert_no_open_grievance(context: ReleaseContext) -> None:
    """An undisposed dispute on *this* entitlement blocks *its* release."""
    if context.open_grievance_ids:
        raise GrievanceOpen(
            f"entitlement {context.entitlement_id} has "
            f"{len(context.open_grievance_ids)} open grievance(s). Disposition them "
            "before releasing: paying an amount a household has already disputed is how a "
            "complaint becomes a second complaint."
        )


async def release(
    context: ReleaseContext,
    *,
    principal: Principal,
    rail: PaymentRail,
) -> ReleaseDecision:
    """Run every check, then move the money.

    The caller is responsible for having verified `Scope.DISBURSEMENT_RELEASE` for the
    entitlement's district before reaching here - that belongs with the endpoint, which
    knows how to resolve an area. Everything after it belongs here.

    Note there is no amount parameter. The amount is `context.amount_lkr_cents`, which
    came from the entitlement's own calculation.
    """
    assert_not_released(context)
    assert_step_up(principal)

    releaser_id = UUID(principal.subject_id)
    assert_segregation(context, releaser_id)
    assert_approvals_complete(context)
    assert_no_open_grievance(context)

    at = utc_now()
    reference = f"SARANA-{context.entitlement_id}"

    try:
        payment_ref = await rail.send(
            amount_lkr_cents=context.amount_lkr_cents, reference=reference
        )
    except Exception as error:
        # Nothing is written. A ledger entry for a payment that did not leave would be a
        # household told they were paid and a reconciliation that never balances.
        raise ReleaseRefused(
            f"the payment rail refused this release: {error}. Nothing has been recorded."
        ) from error

    _log.info(
        "disbursement_released",
        entitlement_id=str(context.entitlement_id),
        amount_lkr_cents=context.amount_lkr_cents,
        released_by=str(releaser_id),
        rail=rail.name,
    )
    return ReleaseDecision(
        entitlement_id=context.entitlement_id,
        amount_lkr_cents=context.amount_lkr_cents,
        released_by=releaser_id,
        at=at,
        payment_ref=payment_ref,
    )
