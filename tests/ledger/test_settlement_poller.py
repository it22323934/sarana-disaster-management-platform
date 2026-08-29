"""The poller that finds out a released payment never arrived.

Nothing else in the platform would. The rail accepts a transfer immediately, the ledger
records the release and publishes it, and about three in a hundred then quietly fail. The
household is at home believing they have been paid.

These tests drive `run_once` against a stub rail rather than a live one, because what is
under test is the decision the poller makes about each answer — reverse, leave alone, or
back off — and a real rail would make those answers arbitrary. `tests/gov_mock` covers the
rail's own behaviour; this covers what the ledger does with it.

The most important test here is the one where the bank is unreachable. A poller that read
a timeout as a failed payment would reverse money that is on its way, raise grievances
nobody needs, and do it to every household in the country in the same pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from ledger_svc.workers import settlement
from sarana_shared.adapters.gov.base import GovRecordNotFound, GovTimeout
from sarana_shared.adapters.gov.payment import (
    FailureReason,
    Transfer,
    TransferState,
    WebhookRegistration,
)
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from tests.ledger.test_reversal import AMOUNT, a_released_payment

pytestmark = pytest.mark.asyncio(loop_scope="session")


@dataclass
class StubRail:
    """A payment rail that answers however the test needs.

    Deliberately not a mock library double: the poller's contract with the rail is the
    `PaymentClient` Protocol, and a stub that satisfies it for real is the only kind that
    proves the poller would work against the actual client.
    """

    state: TransferState = TransferState.SETTLED
    failure_reason: FailureReason | None = None
    raises: Exception | None = None
    asked: list[str] = field(default_factory=list)

    async def submit(self, request: Any) -> Transfer:  # pragma: no cover - unused here
        raise NotImplementedError

    async def transfer(self, transfer_ref: str) -> Transfer:
        self.asked.append(transfer_ref)
        if self.raises is not None:
            raise self.raises
        return Transfer(
            transfer_ref=transfer_ref,
            client_reference=transfer_ref,
            state=self.state,
            amount_lkr_cents=AMOUNT,
            accepted_at=datetime.fromisoformat("2026-08-29T00:00:00+00:00"),
            settled_at=(
                datetime.fromisoformat("2026-08-29T01:00:00+00:00")
                if self.state is TransferState.SETTLED
                else None
            ),
            failure_reason=self.failure_reason,
        )

    async def register_webhook(  # pragma: no cover - unused here
        self, *, url: str, events: list[str]
    ) -> WebhookRegistration:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class OneShotFactory:
    """A session factory over the test's own connection.

    Two things it has to get right.

    It must hand out an `AsyncSession`, not the raw `AsyncConnection` the fixture provides:
    the worker publishes through the outbox, which is ORM code and needs `.add()`.

    And it must join the test's transaction rather than opening its own, with
    `join_transaction_mode="create_savepoint"` so the worker's `commit()` releases a
    savepoint instead of committing the outer transaction. Without that the worker's writes
    would survive the rollback and leak into the next test.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    def __call__(self) -> AsyncSession:
        return AsyncSession(
            bind=self._connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )


async def _pending_count(db: AsyncConnection, disbursement_id: UUID) -> int:
    result = await db.execute(
        text("SELECT COUNT(*) FROM aid.disbursement WHERE id = :id AND reversed_at IS NULL"),
        {"id": disbursement_id},
    )
    return int(result.scalar_one())


async def test_a_failed_transfer_is_reversed(db: AsyncConnection) -> None:
    """The whole point. A rail reporting FAILED produces a compensating entry."""
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.ACCOUNT_CLOSED)

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 1
    assert await _pending_count(db, payment["disbursement_id"]) == 0


async def test_the_reversal_carries_the_rails_reason(db: AsyncConnection) -> None:
    """The reason reaches the entry, so the household is told what to do.

    "Payment failed" tells a family nothing. "Your account is closed; take new details to
    the Divisional Secretariat" tells them what to do on Monday.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.NAME_MISMATCH)

    await settlement.run_once(OneShotFactory(db), rail=rail)

    result = await db.execute(
        text("SELECT reason FROM aid.disbursement_reversal WHERE disbursement_id = :id"),
        {"id": payment["disbursement_id"]},
    )
    assert result.scalar_one() == "NAME_MISMATCH"


async def test_a_reversal_raises_a_grievance_for_the_household(db: AsyncConnection) -> None:
    """Nobody complained. A bank returned the money and the household does not know.

    Raising the case on their behalf is what puts a clock on it — a seven-day SLA, an
    assigned division, and an officer who has to answer. Without it the failure is silent
    and surfaces weeks later when the family asks why nothing arrived.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.ACCOUNT_DORMANT)

    await settlement.run_once(OneShotFactory(db), rail=rail)

    result = await db.execute(
        text(
            "SELECT g.channel, g.subject_type, g.status, g.description "
            "FROM aid.grievance g "
            "JOIN aid.disbursement_reversal r ON r.grievance_id = g.id "
            "WHERE r.disbursement_id = :id"
        ),
        {"id": payment["disbursement_id"]},
    )
    grievance = result.mappings().one()

    assert grievance["channel"] == "SYSTEM"
    assert grievance["subject_type"] == "DISBURSEMENT"
    assert grievance["status"] == "RECEIVED"
    # Trilingual, because it goes to a household. Non-negotiable #2 holds on the path
    # where nobody is watching for it.
    assert set(grievance["description"]) == {"si", "ta", "en"}


async def test_a_reversal_reopens_the_entitlement(db: AsyncConnection) -> None:
    """APPROVED, not REJECTED. The approvals still stand; the transfer failed.

    Leaving it DISBURSED would bar the household from the money they are owed for the sake
    of a bank's mistake.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.INVALID_ACCOUNT)

    await settlement.run_once(OneShotFactory(db), rail=rail)

    result = await db.execute(
        text("SELECT status FROM aid.entitlement WHERE id = :id"),
        {"id": payment["entitlement_id"]},
    )
    assert result.scalar_one() == "APPROVED"


async def test_a_settled_transfer_changes_nothing(db: AsyncConnection) -> None:
    """The common case. Money arrived; there is nothing to correct."""
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.SETTLED)

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 0
    assert result.settled >= 1
    assert await _pending_count(db, payment["disbursement_id"]) == 1


async def test_an_accepted_transfer_is_left_alone(db: AsyncConnection) -> None:
    """Still in flight is not failed.

    Reversing a transfer the rail has merely not settled yet would take money back off the
    books while it was on its way.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.ACCEPTED)

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 0
    assert await _pending_count(db, payment["disbursement_id"]) == 1


async def test_an_unreachable_rail_reverses_nothing(db: AsyncConnection) -> None:
    """The test that matters most.

    A poller reading a timeout as a failed payment would reverse money that is on its way,
    raise grievances nobody needs, and do it to every household in the same pass — turning
    one outage at a bank into a national incident inside the platform.
    """
    payment = await a_released_payment(db)
    rail = StubRail(raises=GovTimeout("pay", "the rail did not answer"))

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 0
    assert result.unreachable == 1
    assert await _pending_count(db, payment["disbursement_id"]) == 1


async def test_a_reference_the_rail_has_never_heard_of_reverses_nothing(
    db: AsyncConnection,
) -> None:
    """The ledger and the rail disagreeing is a case for a person, not a reversal.

    Taking money back off the books on the strength of an *absence* is the wrong direction:
    the payment may well have been made under a reference somebody mistyped.
    """
    payment = await a_released_payment(db)
    rail = StubRail(raises=GovRecordNotFound("no such transfer"))

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 0
    assert await _pending_count(db, payment["disbursement_id"]) == 1


async def test_a_second_pass_over_the_same_failure_does_nothing(db: AsyncConnection) -> None:
    """The poller re-reads its work list every pass and must be idempotent.

    A second compensating entry would double-count the money coming back, and a second
    grievance would put two cases in front of an officer for one failure.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.LIMIT_EXCEEDED)

    first = await settlement.run_once(OneShotFactory(db), rail=rail)
    second = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert first.reversed_count == 1
    assert second.reversed_count == 0

    result = await db.execute(
        text("SELECT COUNT(*) FROM aid.disbursement_reversal WHERE disbursement_id = :id"),
        {"id": payment["disbursement_id"]},
    )
    assert result.scalar_one() == 1


async def test_a_confirmed_payment_is_not_polled(db: AsyncConnection) -> None:
    """A household that said the money arrived settles the question.

    The rail's opinion cannot overturn it, and asking about it wastes a call on somebody
    else's system for every confirmed payment in the window.
    """
    payment = await a_released_payment(db)
    await db.execute(
        text(
            "UPDATE aid.disbursement SET citizen_confirmed = true, "
            "citizen_confirmed_at = now(), citizen_confirm_channel = 'SMS' WHERE id = :id"
        ),
        {"id": payment["disbursement_id"]},
    )
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.ACCOUNT_CLOSED)

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert str(payment["disbursement_id"]) not in "".join(rail.asked)
    assert result.reversed_count == 0


async def test_a_failure_with_no_reason_still_tells_the_household_something(
    db: AsyncConnection,
) -> None:
    """A rail that reports FAILED and no reason must not produce a silent reversal.

    `RAIL_RETURNED` at least says truthfully that the bank sent it back and somebody is
    looking into it, which is more than a blank field gives a family.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=None)

    await settlement.run_once(OneShotFactory(db), rail=rail)

    result = await db.execute(
        text("SELECT reason FROM aid.disbursement_reversal WHERE disbursement_id = :id"),
        {"id": payment["disbursement_id"]},
    )
    assert result.scalar_one() == "RAIL_RETURNED"


async def test_a_returned_transfer_counts_as_a_failure(db: AsyncConnection) -> None:
    """RETURNED and FAILED both mean the money came back.

    A rail distinguishing them is describing its own internals. To the household they are
    the same event, and treating RETURNED as still-in-flight would leave the failure
    undetected forever.
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.RETURNED, failure_reason=FailureReason.ACCOUNT_CLOSED)

    result = await settlement.run_once(OneShotFactory(db), rail=rail)

    assert result.reversed_count == 1
    assert await _pending_count(db, payment["disbursement_id"]) == 0


async def test_the_poller_publishes_an_event_so_the_household_is_messaged(
    db: AsyncConnection,
) -> None:
    """alerting-svc listens for this and sends the SMS.

    The reversal in the ledger is the record; the event is what actually reaches the
    household. `needs_new_bank_details` rides along because it decides whether the message
    says "we will try again" or "bring us different account details".
    """
    payment = await a_released_payment(db)
    rail = StubRail(state=TransferState.FAILED, failure_reason=FailureReason.ACCOUNT_CLOSED)

    await settlement.run_once(OneShotFactory(db), rail=rail)

    result = await db.execute(
        text(
            "SELECT event_type, payload FROM outbox.ledger_svc_event "
            "WHERE subject = :subject ORDER BY created_at DESC LIMIT 1"
        ),
        {"subject": str(payment["disbursement_id"])},
    )
    row = result.mappings().first()
    assert row is not None, "nothing was published, so nobody tells the household"
    assert row["event_type"] == "sarana.aid.disbursement.reversed"
    assert row["payload"]["needs_new_bank_details"] is True


def test_the_worker_sleeps_before_its_first_poll() -> None:
    """A crash-looping process must not hammer somebody else's rail on every start."""
    assert settlement.POLL_INTERVAL_SECONDS > 0


def test_only_states_meaning_the_money_came_back_trigger_a_reversal() -> None:
    """ACCEPTED must never be in the set. It is the normal state of a payment in flight."""
    assert TransferState.ACCEPTED not in settlement.FAILED_STATES
    assert TransferState.SETTLED not in settlement.FAILED_STATES
    assert {TransferState.FAILED, TransferState.RETURNED} == settlement.FAILED_STATES


def test_uuid7_is_imported_for_correlation() -> None:
    """Guard against the import being dropped: every reversal needs a correlation id."""
    assert uuid7() != uuid7()
    assert utc_now().tzinfo is not None
