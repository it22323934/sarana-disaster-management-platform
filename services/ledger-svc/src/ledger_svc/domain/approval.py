"""Who has to approve an entitlement, and when one signature is not enough.

DS approves. Above a configurable threshold the District Secretariat has to approve as
well. The threshold is the whole point of having two levels: below it, requiring a second
signature would put a district officer in the path of thousands of small household
payments and slow every one of them down. Above it, a single signature is too much
authority for one person during a period when nobody is checking carefully.

Segregation of duty is enforced alongside this, in the domain layer and again as a
database trigger. This module answers "is this entitlement ready to disburse"; the
trigger answers "is this particular person allowed to be the one signing".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from sarana_shared.domain.money import LKRCents, format_lkr

# LKR 500,000 in minor units. Set here as the default and overridable per deployment: the
# right threshold is a policy decision for the NDRSC, not an engineering one.
DEFAULT_DISTRICT_THRESHOLD_CENTS: Final[LKRCents] = 50_000_000


class ApprovalLevel(StrEnum):
    """The two levels, named after the offices that hold them."""

    DS = "DS"
    DISTRICT = "DISTRICT"


class ApprovalIncomplete(Exception):
    """The entitlement does not yet carry every approval it needs."""


class SelfApproval(Exception):
    """The same person would be signing twice, or signing their own assessment."""


def required_levels(
    amount_lkr_cents: LKRCents,
    *,
    threshold_cents: LKRCents = DEFAULT_DISTRICT_THRESHOLD_CENTS,
) -> frozenset[ApprovalLevel]:
    """Which approval levels an amount needs before it can be released.

    The same rule `ApprovalState.is_fully_approved` applies, expressed over an amount
    alone so a queue can ask the question without loading every approver id. Both read
    this threshold, so a queue that says an entitlement is ready and a gate that then
    refuses it cannot disagree.
    """
    if amount_lkr_cents > threshold_cents:
        return frozenset({ApprovalLevel.DS, ApprovalLevel.DISTRICT})
    return frozenset({ApprovalLevel.DS})


def is_ready_to_release(
    amount_lkr_cents: LKRCents,
    approved_levels: Iterable[str],
    *,
    threshold_cents: LKRCents = DEFAULT_DISTRICT_THRESHOLD_CENTS,
) -> bool:
    """Whether the recorded approvals cover every level this amount needs.

    Levels, not a count. Two approvals at the same level are not two levels, and a queue
    that counted rows would offer an approver work the gate is about to refuse.
    """
    recorded = {str(level) for level in approved_levels}
    return all(
        level.value in recorded
        for level in required_levels(amount_lkr_cents, threshold_cents=threshold_cents)
    )


@dataclass(frozen=True, slots=True)
class ApprovalState:
    """What has been approved on one entitlement so far."""

    amount_lkr_cents: LKRCents
    assessed_by: UUID
    ds_approver_id: UUID | None = None
    district_approver_id: UUID | None = None

    def requires_district(
        self, *, threshold_cents: LKRCents = DEFAULT_DISTRICT_THRESHOLD_CENTS
    ) -> bool:
        """Whether this amount needs the second level."""
        return self.amount_lkr_cents > threshold_cents

    def is_fully_approved(
        self, *, threshold_cents: LKRCents = DEFAULT_DISTRICT_THRESHOLD_CENTS
    ) -> bool:
        """Whether every approval this entitlement needs is recorded."""
        if self.ds_approver_id is None:
            return False
        if self.requires_district(threshold_cents=threshold_cents):
            return self.district_approver_id is not None
        return True

    def assert_ready_to_disburse(
        self, *, threshold_cents: LKRCents = DEFAULT_DISTRICT_THRESHOLD_CENTS
    ) -> None:
        """Raise unless the entitlement carries every signature it needs.

        Raises:
            ApprovalIncomplete: naming the missing level and the threshold, so the
                operator sees why rather than being told to try again.
        """
        if self.ds_approver_id is None:
            raise ApprovalIncomplete(
                "This entitlement has not been approved by the Divisional Secretariat."
            )
        if self.requires_district(threshold_cents=threshold_cents) and (
            self.district_approver_id is None
        ):
            raise ApprovalIncomplete(
                f"{format_lkr(self.amount_lkr_cents)} is above the "
                f"{format_lkr(threshold_cents)} threshold and needs District Secretariat "
                "approval as well as Divisional Secretariat approval."
            )

    def assert_may_approve(self, approver_id: UUID, level: ApprovalLevel) -> None:
        """Raise if this person may not add this approval.

        Raises:
            SelfApproval: if they assessed the damage, or already approved at the other
                level. Both are the same failure - one person supplying two of the
                independent judgements the payment rests on.
        """
        if approver_id == self.assessed_by:
            raise SelfApproval(
                "You assessed the damage behind this entitlement and cannot also approve "
                "it. A second person has to review the assessment."
            )

        other = self.district_approver_id if level is ApprovalLevel.DS else self.ds_approver_id
        if other is not None and other == approver_id:
            raise SelfApproval(
                "You have already approved this entitlement at the other level. The "
                "second level exists to be a second pair of eyes."
            )
