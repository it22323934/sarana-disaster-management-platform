"""The approval and release queue rule.

`GET /entitlements` is what a district approver asks "what is waiting". Before it existed
the console had no way to ask, and a screen showing an empty list would have told an
approver no money was waiting when there might have been a hundred households.

The rule it filters on is `domain.approval.is_ready_to_release`, which is deliberately the
same rule the disbursement gate refuses with. These tests exist because the failure mode of
a second copy is specific and nasty: a queue that offers work the gate then rejects teaches
approvers that refusals are noise, which is exactly the habit the gate cannot afford.
"""

from __future__ import annotations

import pytest

from ledger_svc.domain.approval import (
    DEFAULT_DISTRICT_THRESHOLD_CENTS,
    ApprovalLevel,
    ApprovalState,
    is_ready_to_release,
    required_levels,
)
from sarana_shared.domain.ids import uuid7

BELOW = DEFAULT_DISTRICT_THRESHOLD_CENTS - 1
AT = DEFAULT_DISTRICT_THRESHOLD_CENTS
ABOVE = DEFAULT_DISTRICT_THRESHOLD_CENTS + 1


class TestRequiredLevels:
    def test_small_amounts_need_only_the_divisional_secretariat(self) -> None:
        assert required_levels(BELOW) == frozenset({ApprovalLevel.DS})

    def test_the_threshold_itself_is_below_the_line(self) -> None:
        """`>` not `>=`, matching `ApprovalState.requires_district`.

        An off-by-one here would send every entitlement at exactly the threshold to a
        district approver who does not need to see it, or worse, let one past that does.
        """
        assert required_levels(AT) == frozenset({ApprovalLevel.DS})
        assert ApprovalLevel.DISTRICT in required_levels(ABOVE)

    def test_large_amounts_need_both_levels(self) -> None:
        assert required_levels(ABOVE) == frozenset({ApprovalLevel.DS, ApprovalLevel.DISTRICT})


class TestIsReadyToRelease:
    def test_nothing_approved_is_not_ready(self) -> None:
        assert not is_ready_to_release(BELOW, [])

    def test_a_small_amount_is_ready_with_the_ds_signature(self) -> None:
        assert is_ready_to_release(BELOW, ["DS"])

    def test_a_large_amount_is_not_ready_with_only_the_ds_signature(self) -> None:
        assert not is_ready_to_release(ABOVE, ["DS"])

    def test_a_large_amount_is_ready_with_both(self) -> None:
        assert is_ready_to_release(ABOVE, ["DS", "DISTRICT"])

    def test_two_approvals_at_the_same_level_are_not_two_levels(self) -> None:
        """The reason this takes levels rather than a count.

        A queue that counted approval rows would call this ready. The gate, which checks
        levels, would then refuse it - and the approver would learn that refusals are
        noise, which is the one habit a human gate cannot afford.
        """
        assert not is_ready_to_release(ABOVE, ["DS", "DS"])

    def test_a_district_signature_alone_is_not_enough(self) -> None:
        """DS is required at every amount; district is the *additional* level."""
        assert not is_ready_to_release(ABOVE, ["DISTRICT"])
        assert not is_ready_to_release(BELOW, ["DISTRICT"])

    def test_unknown_levels_are_ignored_rather_than_counted(self) -> None:
        """A level this code does not know about cannot satisfy one it does.

        Defensive because the column is text: a future level added to the database and not
        to this enum must not silently make an entitlement releasable.
        """
        assert not is_ready_to_release(BELOW, ["PROVINCIAL"])


class TestAgreementWithTheGate:
    """The queue and the gate must answer identically, at every amount that matters."""

    @pytest.mark.parametrize("amount", [1, BELOW, AT, ABOVE, 10 * DEFAULT_DISTRICT_THRESHOLD_CENTS])
    @pytest.mark.parametrize(
        "levels",
        [[], ["DS"], ["DISTRICT"], ["DS", "DISTRICT"]],
        ids=["none", "ds", "district", "both"],
    )
    def test_queue_and_gate_agree(self, amount: int, levels: list[str]) -> None:
        """`is_ready_to_release` and `ApprovalState.is_fully_approved` never disagree.

        This is the test that matters. The queue reads the first, the gate reads the
        second, and the whole reason for putting the rule in one module is that these two
        answers are the same answer.
        """
        state = ApprovalState(
            amount_lkr_cents=amount,
            assessed_by=uuid7(),
            ds_approver_id=uuid7() if "DS" in levels else None,
            district_approver_id=uuid7() if "DISTRICT" in levels else None,
        )
        assert is_ready_to_release(amount, levels) == state.is_fully_approved()
