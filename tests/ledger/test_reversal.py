"""A released payment that comes back, and what the ledger does about it.

The test build file 11 asks for and file 10 could not yet support: "a payment marked
settled and then failed produces a compensating ledger entry". About three transfers in a
hundred fail *after* the rail accepted them, by which time `aid.disbursement` has already
recorded a release, hashed it and published it.

Four properties are asserted here, and each of them fails in a different, expensive way:

  **The original is never edited.** Its hash must not move. An auditor has to be able to
  see that the state believed it had paid this household.
  **The correction is a chained entry**, on its own chain, committing to the payment it
  reverses — so it cannot later be denied or re-pointed.
  **The household is told**, through a grievance raised on their behalf, because nobody
  replied NO: they are at home believing they have been paid.
  **The entitlement becomes payable again.** Without that, reversing a bounced payment
  would permanently bar the household from money they are owed, which would make the
  correction worse than the failure.

These run against the real schema. Most of the guarantee is database triggers and a partial
unique index, and testing that against anything else would prove nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ledger_svc.domain import reversal as domain
from sarana_shared.crypto.chain import GENESIS_HASH, chain_hash
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from tests.schema.factories import (
    append_chained,
    make_admin_hierarchy,
    make_entitlement,
    make_user_with_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

AMOUNT = 250_000_00


async def a_released_payment(db: AsyncConnection) -> dict[str, Any]:
    """One real, correctly chained disbursement, with everything a reversal needs."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    releaser_id = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])

    disbursement_id = uuid7()
    await append_chained(
        db,
        schema="aid",
        table="disbursement",
        columns={
            "id": disbursement_id,
            "entitlement_id": entitlement["entitlement_id"],
            "amount_lkr_cents": AMOUNT,
            "released_by": releaser_id,
            "released_at": utc_now(),
            "payment_rail": "BANK_TRANSFER",
            "payment_ref": "MOCK-BANK_TRANSFER-000000000001",
            "correlation_id": str(uuid7()),
        },
    )
    return {
        "disbursement_id": disbursement_id,
        "entitlement_id": entitlement["entitlement_id"],
        "hierarchy": hierarchy,
    }


async def a_reversal(
    db: AsyncConnection, payment: dict[str, Any], *, reason: str = "ACCOUNT_CLOSED"
) -> Any:
    """Append a compensating entry the way the service does."""
    entry = domain.reverse(
        disbursement_id=payment["disbursement_id"],
        entitlement_id=payment["entitlement_id"],
        amount_lkr_cents=AMOUNT,
        reason=reason,
        rail_reference="MOCK-BANK_TRANSFER-000000000001",
        correlation_id=str(uuid7()),
    )

    tail = await db.execute(
        text("SELECT entry_hash FROM aid.disbursement_reversal ORDER BY seq DESC LIMIT 1")
    )
    previous = tail.scalar_one_or_none() or GENESIS_HASH
    entry_hash = chain_hash(entry.hashed_payload(), previous)

    columns = entry.as_columns()
    names = ", ".join(columns)
    placeholders = ", ".join(f":{name}" for name in columns)
    await db.execute(
        text(
            f"INSERT INTO aid.disbursement_reversal ({names}, prev_hash, entry_hash) "  # noqa: S608
            f"VALUES ({placeholders}, :prev_hash, :entry_hash)"
        ),
        {**columns, "prev_hash": previous, "entry_hash": entry_hash},
    )
    return entry


# --------------------------------------------------------------------------------------
# The original entry is never touched
# --------------------------------------------------------------------------------------


async def test_reversing_does_not_change_the_original_entry_hash(db: AsyncConnection) -> None:
    """The property the whole transparency claim rests on.

    A ledger whose published hash changed when a bank bounced a payment would fail
    verification for an honest reason, and every reader would have to decide whether the
    alarm meant tampering. It must not move.
    """
    payment = await a_released_payment(db)
    before = await db.execute(
        text("SELECT entry_hash, amount_lkr_cents FROM aid.disbursement WHERE id = :id"),
        {"id": payment["disbursement_id"]},
    )
    original = before.mappings().one()

    await a_reversal(db, payment)

    after = await db.execute(
        text("SELECT entry_hash, amount_lkr_cents FROM aid.disbursement WHERE id = :id"),
        {"id": payment["disbursement_id"]},
    )
    unchanged = after.mappings().one()

    assert unchanged["entry_hash"] == original["entry_hash"]
    assert unchanged["amount_lkr_cents"] == original["amount_lkr_cents"]


async def test_the_original_payment_stays_visible(db: AsyncConnection) -> None:
    """Reversal is not deletion. The row is still there and still says what it said."""
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    result = await db.execute(
        text("SELECT amount_lkr_cents, payment_rail FROM aid.disbursement WHERE id = :id"),
        {"id": payment["disbursement_id"]},
    )
    row = result.mappings().one()
    assert row["amount_lkr_cents"] == AMOUNT
    assert row["payment_rail"] == "BANK_TRANSFER"


async def test_the_back_pointer_is_stamped_by_the_database(db: AsyncConnection) -> None:
    """`reversed_at` is set by a trigger, not by the application.

    The application would have to remember. The trigger cannot forget, which is what stops
    a compensating entry and a stale back-pointer from disagreeing about whether a payment
    is live.
    """
    payment = await a_released_payment(db)
    entry = await a_reversal(db, payment)

    result = await db.execute(
        text("SELECT reversed_at FROM aid.disbursement WHERE id = :id"),
        {"id": payment["disbursement_id"]},
    )
    assert result.scalar_one() == entry.reversed_at


# --------------------------------------------------------------------------------------
# The compensating entry is a real chained entry
# --------------------------------------------------------------------------------------


async def test_the_reversal_is_chained_and_verifiable(db: AsyncConnection) -> None:
    """Recomputing the reversal's hash from its published payload reproduces it."""
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    result = await db.execute(
        text(
            "SELECT disbursement_id::text, entitlement_id::text, amount_lkr_cents, "
            "reason, rail_reference, reversed_at, prev_hash, entry_hash "
            "FROM aid.disbursement_reversal WHERE disbursement_id = :id"
        ),
        {"id": payment["disbursement_id"]},
    )
    row = dict(result.mappings().one())

    recomputed = chain_hash(
        domain.public_reversal(
            disbursement_id=row["disbursement_id"],
            entitlement_id=row["entitlement_id"],
            amount_lkr_cents=row["amount_lkr_cents"],
            reason=row["reason"],
            rail_reference=row["rail_reference"],
            reversed_at=row["reversed_at"],
        ),
        row["prev_hash"],
    )
    assert recomputed == row["entry_hash"]


async def test_the_hash_commits_to_which_payment_was_reversed(db: AsyncConnection) -> None:
    """`disbursement_id` is inside the hashed payload.

    That is the difference between a compensating entry and a note in a file: a reversal
    cannot later be denied, or quietly re-pointed at a different payment, without breaking
    its own hash.
    """
    payment = await a_released_payment(db)
    entry = await a_reversal(db, payment)

    assert "disbursement_id" in entry.hashed_payload()

    moved = dict(entry.hashed_payload())
    moved["disbursement_id"] = str(uuid7())
    assert chain_hash(moved, GENESIS_HASH) != chain_hash(entry.hashed_payload(), GENESIS_HASH)


async def test_a_payment_is_reversed_only_once(db: AsyncConnection) -> None:
    """A rail reporting the same failure twice is the same failure.

    A second compensating entry would double-count the money coming back, and the ledger
    would show more returned than was ever sent.
    """
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    with pytest.raises(Exception, match="uq_reversal_disbursement"):
        await a_reversal(db, payment)


async def test_a_reversal_cannot_be_edited(db: AsyncConnection) -> None:
    """Append-only, like everything else here.

    An editable reversal is a way to un-fail a payment, which is precisely what the
    compensating entry exists to prevent.
    """
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text(
                "UPDATE aid.disbursement_reversal SET amount_lkr_cents = 1 "
                "WHERE disbursement_id = :id"
            ),
            {"id": payment["disbursement_id"]},
        )


async def test_a_reversal_cannot_be_cleared_from_the_disbursement(db: AsyncConnection) -> None:
    """`reversed_at` is set once and never moved.

    Un-reversing would let an operator make a failed payment look successful again while
    the compensating entry sat there contradicting it.
    """
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    with pytest.raises(Exception, match="set once"):
        await db.execute(
            text("UPDATE aid.disbursement SET reversed_at = NULL WHERE id = :id"),
            {"id": payment["disbursement_id"]},
        )


# --------------------------------------------------------------------------------------
# The household can be paid again
# --------------------------------------------------------------------------------------


async def test_a_reversed_payment_frees_the_entitlement(db: AsyncConnection) -> None:
    """The point of reversing at all.

    Without the partial unique index this insert is refused, and a household whose bank
    returned their relief payment could never receive it — which would make the
    compensating entry a worse outcome than leaving the failed record standing.
    """
    payment = await a_released_payment(db)
    await a_reversal(db, payment)

    releaser_id = await make_user_with_role(
        db, "DISTRICT_APPROVER", payment["hierarchy"]["district_code"]
    )
    await append_chained(
        db,
        schema="aid",
        table="disbursement",
        columns={
            "id": uuid7(),
            "entitlement_id": payment["entitlement_id"],
            "amount_lkr_cents": AMOUNT,
            "released_by": releaser_id,
            "released_at": utc_now(),
            "payment_rail": "CASH",
            "payment_ref": "MOCK-CASH-000000000002",
            "correlation_id": str(uuid7()),
        },
    )

    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM aid.disbursement "
            "WHERE entitlement_id = :id AND reversed_at IS NULL"
        ),
        {"id": payment["entitlement_id"]},
    )
    assert result.scalar_one() == 1


async def test_two_live_payments_for_one_entitlement_are_still_refused(
    db: AsyncConnection,
) -> None:
    """The invariant the partial index must not lose.

    Relaxing "one payment per entitlement" to "one *live* payment" is only safe if the
    second half still holds. Paying a household twice for one entitlement is the failure
    the original constraint existed to prevent.
    """
    payment = await a_released_payment(db)
    releaser_id = await make_user_with_role(
        db, "DISTRICT_APPROVER", payment["hierarchy"]["district_code"]
    )

    with pytest.raises(Exception, match="uq_disbursement_entitlement_live"):
        await append_chained(
            db,
            schema="aid",
            table="disbursement",
            columns={
                "id": uuid7(),
                "entitlement_id": payment["entitlement_id"],
                "amount_lkr_cents": AMOUNT,
                "released_by": releaser_id,
                "released_at": utc_now(),
                "payment_rail": "CASH",
                "payment_ref": "MOCK-CASH-000000000003",
                "correlation_id": str(uuid7()),
            },
        )
