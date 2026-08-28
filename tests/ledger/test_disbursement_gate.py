"""The disbursement human gate.

Releasing money is irreversible in practice, so these are written as attempts to get
money out of the system rather than as happy paths. Each names a specific way a payment
could be released that should not be, and asserts it is refused.

The brief names three explicitly — release without a fresh step-up, with an open
grievance, and by the assessor — and each is here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from ledger_svc.domain.disbursement_gate import (
    DISTRICT_APPROVAL_THRESHOLD_CENTS,
    AlreadyReleased,
    Approval,
    ApprovalLevel,
    ApprovalsIncomplete,
    GrievanceOpen,
    ReleaseContext,
    ReleaseRefused,
    SegregationViolated,
    StepUpRequired,
    release,
)
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, Role, Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

pytestmark = pytest.mark.asyncio(loop_scope="session")

ASSESSOR = uuid7()
DS_APPROVER = uuid7()
DISTRICT_APPROVER = uuid7()


def releaser(subject_id: Any = None, *, stepped_up_minutes_ago: float | None = 0.0) -> Principal:
    step_up_at = (
        None
        if stepped_up_minutes_ago is None
        else utc_now() - timedelta(minutes=stepped_up_minutes_ago)
    )
    return Principal(
        subject_id=str(subject_id or uuid7()),
        roles=frozenset({Role.DISTRICT_APPROVER}),
        grants=grants_for_assignments([(Role.DISTRICT_APPROVER, ScopeType.NATIONAL, "LK")]),
        step_up_at=step_up_at,
    )


def a_context(**overrides: Any) -> ReleaseContext:
    fields: dict[str, Any] = {
        "entitlement_id": uuid7(),
        "amount_lkr_cents": 47_500_00,
        "district_code": "LK-21",
        "assessor_id": ASSESSOR,
        "approvals": [Approval(ApprovalLevel.DS, DS_APPROVER, "APPROVED")],
        "open_grievance_ids": [],
    }
    fields.update(overrides)
    return ReleaseContext(**fields)


class MockRail:
    """A payment rail that succeeds. Its reference says it is a mock."""

    name = "MOCK_BANK_TRANSFER"

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send(self, *, amount_lkr_cents: int, reference: str) -> str:
        self.sent.append((amount_lkr_cents, reference))
        return f"mock-{reference}"


class FailingRail:
    name = "MOCK_BANK_TRANSFER"

    async def send(self, *, amount_lkr_cents: int, reference: str) -> str:
        raise RuntimeError("the bank rejected the transfer")


# --------------------------------------------------------------------------------------
# The scope itself
# --------------------------------------------------------------------------------------


def test_releasing_money_is_one_of_the_two_mandatory_human_gates() -> None:
    assert Scope.DISBURSEMENT_RELEASE in HUMAN_GATE_SCOPES


def test_a_machine_principal_can_never_hold_the_release_scope() -> None:
    """Stripped at mint time, so no configuration mistake can grant it."""
    from sarana_shared.auth.grants import strip_human_gates

    granted = grants_for_assignments([(Role.AGENT, ScopeType.NATIONAL, "LK")])

    assert not any(
        grant.scope is Scope.DISBURSEMENT_RELEASE for grant in strip_human_gates(granted)
    )


# --------------------------------------------------------------------------------------
# The happy path, so the refusals below mean something
# --------------------------------------------------------------------------------------


async def test_a_properly_approved_entitlement_is_released() -> None:
    rail = MockRail()

    decision = await release(a_context(), principal=releaser(), rail=rail)

    assert decision.amount_lkr_cents == 47_500_00
    assert decision.payment_ref
    assert rail.sent


async def test_the_amount_comes_from_the_entitlement_not_the_caller() -> None:
    """There is no amount parameter, deliberately.

    A releaser who could type a number would make the calculation trace decorative.
    """
    rail = MockRail()
    context = a_context(amount_lkr_cents=12_345_00)

    decision = await release(context, principal=releaser(), rail=rail)

    assert decision.amount_lkr_cents == 12_345_00
    assert rail.sent[0][0] == 12_345_00


# --------------------------------------------------------------------------------------
# Step-up
# --------------------------------------------------------------------------------------


async def test_release_without_a_step_up_is_refused() -> None:
    """The case the brief names. A session alone is never sufficient."""
    with pytest.raises(StepUpRequired):
        await release(
            a_context(),
            principal=releaser(stepped_up_minutes_ago=None),
            rail=MockRail(),
        )


async def test_a_step_up_older_than_the_window_is_refused() -> None:
    """Being logged in when the entitlement arrived is not deciding to pay it."""
    with pytest.raises(StepUpRequired):
        await release(a_context(), principal=releaser(stepped_up_minutes_ago=6), rail=MockRail())


async def test_a_recent_step_up_is_accepted() -> None:
    decision = await release(
        a_context(), principal=releaser(stepped_up_minutes_ago=4), rail=MockRail()
    )

    assert decision.payment_ref


async def test_a_failed_step_up_moves_no_money() -> None:
    """A refused release must leave nothing behind, including at the rail."""
    rail = MockRail()

    with pytest.raises(StepUpRequired):
        await release(a_context(), principal=releaser(stepped_up_minutes_ago=None), rail=rail)

    assert rail.sent == []


# --------------------------------------------------------------------------------------
# Segregation of duty
# --------------------------------------------------------------------------------------


async def test_the_assessor_cannot_release_the_payment() -> None:
    """The case the brief names, and the fraud the approval chain exists to prevent.

    One person who can assess, approve and pay needs no accomplice and leaves no
    disagreement in the record.
    """
    with pytest.raises(SegregationViolated, match="assessed this damage"):
        await release(a_context(), principal=releaser(ASSESSOR), rail=MockRail())


async def test_the_ds_approver_cannot_release_the_payment() -> None:
    with pytest.raises(SegregationViolated, match="DS approver"):
        await release(a_context(), principal=releaser(DS_APPROVER), rail=MockRail())


async def test_the_district_approver_cannot_release_the_payment() -> None:
    context = a_context(
        amount_lkr_cents=DISTRICT_APPROVAL_THRESHOLD_CENTS + 1,
        approvals=[
            Approval(ApprovalLevel.DS, DS_APPROVER, "APPROVED"),
            Approval(ApprovalLevel.DISTRICT, DISTRICT_APPROVER, "APPROVED"),
        ],
    )

    with pytest.raises(SegregationViolated, match="DISTRICT approver"):
        await release(context, principal=releaser(DISTRICT_APPROVER), rail=MockRail())


async def test_someone_whose_approval_was_superseded_may_release() -> None:
    """A superseded approval is not a current decision.

    Segregation exists to keep a *live* decision separate from its payment; blocking
    somebody over a decision that no longer stands would remove releasers for no gain.
    """
    person = uuid7()
    context = a_context(
        approvals=[
            Approval(ApprovalLevel.DS, person, "APPROVED", superseded=True),
            Approval(ApprovalLevel.DS, DS_APPROVER, "APPROVED"),
        ]
    )

    decision = await release(context, principal=releaser(person), rail=MockRail())

    assert decision.payment_ref


# --------------------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------------------


async def test_release_without_a_ds_approval_is_refused() -> None:
    with pytest.raises(ApprovalsIncomplete, match="DS approval is required"):
        await release(a_context(approvals=[]), principal=releaser(), rail=MockRail())


async def test_a_rejected_approval_does_not_count() -> None:
    context = a_context(approvals=[Approval(ApprovalLevel.DS, DS_APPROVER, "REJECTED")])

    with pytest.raises(ApprovalsIncomplete):
        await release(context, principal=releaser(), rail=MockRail())


async def test_a_superseded_approval_does_not_authorise_the_new_amount() -> None:
    """It approved a different number.

    Recalculation creates a new entitlement; carrying the old approval forward would
    release money nobody agreed to.
    """
    context = a_context(
        approvals=[Approval(ApprovalLevel.DS, DS_APPROVER, "APPROVED", superseded=True)]
    )

    with pytest.raises(ApprovalsIncomplete, match="superseded"):
        await release(context, principal=releaser(), rail=MockRail())


async def test_a_large_entitlement_needs_a_district_approval_too() -> None:
    context = a_context(amount_lkr_cents=DISTRICT_APPROVAL_THRESHOLD_CENTS + 1)

    with pytest.raises(ApprovalsIncomplete, match="district approval is required"):
        await release(context, principal=releaser(), rail=MockRail())


async def test_a_small_entitlement_needs_only_the_ds_approval() -> None:
    """A second pair of eyes on every small payment delays the people least able to wait."""
    context = a_context(amount_lkr_cents=DISTRICT_APPROVAL_THRESHOLD_CENTS - 1)

    decision = await release(context, principal=releaser(), rail=MockRail())

    assert decision.payment_ref


# --------------------------------------------------------------------------------------
# Grievances
# --------------------------------------------------------------------------------------


async def test_an_open_grievance_on_this_entitlement_blocks_its_release() -> None:
    """The case the brief names."""
    context = a_context(open_grievance_ids=[uuid7()])

    with pytest.raises(GrievanceOpen):
        await release(context, principal=releaser(), rail=MockRail())


async def test_a_dispositioned_grievance_does_not_block() -> None:
    """The block is on *open* grievances. A resolved one is a finished conversation."""
    decision = await release(
        a_context(open_grievance_ids=[]), principal=releaser(), rail=MockRail()
    )

    assert decision.payment_ref


# --------------------------------------------------------------------------------------
# Double release and rail failure
# --------------------------------------------------------------------------------------


async def test_an_entitlement_cannot_be_released_twice() -> None:
    """Refused, not silently succeeded.

    The second caller may be a different officer who needs to know it is already done.
    """
    with pytest.raises(AlreadyReleased):
        await release(a_context(already_released=True), principal=releaser(), rail=MockRail())


async def test_a_rail_failure_records_nothing() -> None:
    """A ledger entry for a payment that never left is a household told they were paid
    and a reconciliation that never balances."""
    with pytest.raises(ReleaseRefused, match="Nothing has been recorded"):
        await release(a_context(), principal=releaser(), rail=FailingRail())


# --------------------------------------------------------------------------------------
# The order of the checks
# --------------------------------------------------------------------------------------


async def test_a_double_release_is_caught_before_the_step_up() -> None:
    """Ordering is asserted rather than assumed.

    An already-released entitlement with no step-up raises AlreadyReleased, which proves
    the cheap structural check runs first and neither writes anything.
    """
    with pytest.raises(AlreadyReleased):
        await release(
            a_context(already_released=True),
            principal=releaser(stepped_up_minutes_ago=None),
            rail=MockRail(),
        )


async def test_segregation_is_checked_before_the_approvals_are_counted() -> None:
    """The assessor is refused as the assessor, not told an approval is missing.

    An error message that sent them looking for a missing signature would hide the real
    reason they cannot do this.
    """
    context = a_context(approvals=[])

    with pytest.raises(SegregationViolated):
        await release(context, principal=releaser(ASSESSOR), rail=MockRail())


async def test_no_check_reaches_the_rail_before_it_passes() -> None:
    """Every refusal path leaves the payment rail untouched."""
    rail = MockRail()

    for context, principal in (
        (a_context(already_released=True), releaser()),
        (a_context(), releaser(stepped_up_minutes_ago=None)),
        (a_context(), releaser(ASSESSOR)),
        (a_context(approvals=[]), releaser()),
        (a_context(open_grievance_ids=[uuid7()]), releaser()),
    ):
        with pytest.raises(ReleaseRefused):
            await release(context, principal=principal, rail=rail)

    assert rail.sent == []
