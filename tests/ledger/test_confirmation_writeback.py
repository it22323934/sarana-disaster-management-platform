"""The one permitted UPDATE on the money table.

`aid.disbursement` is append-only twice over - UPDATE revoked from `sarana_app`, and a
trigger that refuses UPDATE from anyone including the owner. That is correct for the
payment and wrong for one thing: the household's answer. The table carries
`citizen_confirmed`, `citizen_confirmed_at` and `citizen_confirm_channel`, and until
migration 0008 nothing could ever set them, so three columns permanently read false and
every query that trusted them under-reported receipt.

0008 narrows the trigger to let exactly those three move, once, forward. These tests are
written as attempts to use that opening for something else, because a narrowed guarantee
is only worth what its narrowest edge holds.

They run against the real schema. The whole property is a database trigger, and testing it
against anything else would prove nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from tests.schema.factories import (
    append_chained,
    make_admin_hierarchy,
    make_entitlement,
    make_user_with_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

AMOUNT = 12_500_00


async def a_disbursement(db: AsyncConnection) -> Any:
    """Write one real, correctly chained disbursement and return its id.

    Built through the shared factories and `append_chained`, so it goes in the way the
    service puts one in: the release-authority trigger checks the releaser's role, and the
    chain trigger requires both hashes supplied against the current tail. A raw INSERT
    would test a path nothing uses.
    """
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
    return disbursement_id


# --------------------------------------------------------------------------------------
# What the opening is for
# --------------------------------------------------------------------------------------


async def test_a_household_confirming_receipt_is_recorded(db: AsyncConnection) -> None:
    """The reason 0008 exists. Without this the confirmation loop had nowhere to write."""
    disbursement_id = await a_disbursement(db)

    await db.execute(
        text(
            "UPDATE aid.disbursement SET citizen_confirmed = true, "
            "citizen_confirmed_at = now(), citizen_confirm_channel = 'SMS' "
            "WHERE id = :id"
        ),
        {"id": disbursement_id},
    )

    result = await db.execute(
        text("SELECT citizen_confirmed FROM aid.disbursement WHERE id = :id"),
        {"id": disbursement_id},
    )
    assert result.scalar_one() is True


async def test_confirming_does_not_change_the_entry_hash(db: AsyncConnection) -> None:
    """The property the whole transparency claim rests on.

    A ledger whose published hash changed when somebody answered an SMS would fail
    verification for an honest reason - the worst kind of alarm, because it trains
    everyone to ignore the real one.
    """
    disbursement_id = await a_disbursement(db)

    before = await db.execute(
        text("SELECT entry_hash FROM aid.disbursement WHERE id = :id"),
        {"id": disbursement_id},
    )
    original = before.scalar_one()

    await db.execute(
        text(
            "UPDATE aid.disbursement SET citizen_confirmed = true, "
            "citizen_confirmed_at = now(), citizen_confirm_channel = 'SMS' "
            "WHERE id = :id"
        ),
        {"id": disbursement_id},
    )

    after = await db.execute(
        text("SELECT entry_hash FROM aid.disbursement WHERE id = :id"),
        {"id": disbursement_id},
    )
    assert after.scalar_one() == original


# --------------------------------------------------------------------------------------
# What it is not for
# --------------------------------------------------------------------------------------


async def test_the_amount_still_cannot_be_changed(db: AsyncConnection) -> None:
    """The single most important thing the append-only rule protects."""
    disbursement_id = await a_disbursement(db)

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text("UPDATE aid.disbursement SET amount_lkr_cents = 1 WHERE id = :id"),
            {"id": disbursement_id},
        )


async def test_the_releaser_still_cannot_be_changed(db: AsyncConnection) -> None:
    """Otherwise the record of who authorised a payment could be reassigned."""
    disbursement_id = await a_disbursement(db)

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text("UPDATE aid.disbursement SET released_by = :who WHERE id = :id"),
            {"id": disbursement_id, "who": uuid7()},
        )


async def test_the_entry_hash_still_cannot_be_rewritten(db: AsyncConnection) -> None:
    """An operator who could rewrite hashes could recompute the whole chain."""
    disbursement_id = await a_disbursement(db)

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text("UPDATE aid.disbursement SET entry_hash = :h WHERE id = :id"),
            {"id": disbursement_id, "h": "ab" * 32},
        )


async def test_a_confirmation_cannot_be_withdrawn(db: AsyncConnection) -> None:
    """Forward only.

    If the household now says the money did not arrive, that is a grievance against this
    disbursement - a new record - not the quiet removal of an answer they already gave.
    """
    disbursement_id = await a_disbursement(db)

    await db.execute(
        text(
            "UPDATE aid.disbursement SET citizen_confirmed = true, "
            "citizen_confirmed_at = now(), citizen_confirm_channel = 'SMS' "
            "WHERE id = :id"
        ),
        {"id": disbursement_id},
    )

    with pytest.raises(Exception, match="cannot be withdrawn"):
        await db.execute(
            text("UPDATE aid.disbursement SET citizen_confirmed = false WHERE id = :id"),
            {"id": disbursement_id},
        )


async def test_a_disbursement_still_cannot_be_deleted(db: AsyncConnection) -> None:
    """Corrections are new compensating entries, never removals."""
    disbursement_id = await a_disbursement(db)

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text("DELETE FROM aid.disbursement WHERE id = :id"), {"id": disbursement_id}
        )


async def test_the_amount_cannot_ride_along_with_a_confirmation(
    db: AsyncConnection,
) -> None:
    """The obvious way to use the opening for something else.

    The trigger compares every other column rather than inspecting which ones the
    statement named, so an UPDATE that sets a confirmation *and* an amount is refused as a
    whole - there is no partial application.
    """
    disbursement_id = await a_disbursement(db)

    # A savepoint, so the connection is usable afterwards: the refusal aborts the
    # transaction, and the assertion that follows is the half that proves nothing was
    # partly applied.
    savepoint = await db.begin_nested()
    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text(
                "UPDATE aid.disbursement SET citizen_confirmed = true, "
                "citizen_confirmed_at = now(), amount_lkr_cents = 999 WHERE id = :id"
            ),
            {"id": disbursement_id},
        )
    await savepoint.rollback()

    result = await db.execute(
        text("SELECT amount_lkr_cents, citizen_confirmed FROM aid.disbursement WHERE id = :id"),
        {"id": disbursement_id},
    )
    amount, confirmed = result.one()
    assert amount == AMOUNT
    assert confirmed is False
