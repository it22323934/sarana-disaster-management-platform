"""The two mandatory human gates, enforced by the database.

SARANA runs autonomously end to end with exactly two mandatory human gates: committing a
life-safety dispatch action, and releasing a financial disbursement. There is no bypass
flag, no demo mode that skips them, and they are not configurable away.

Application-level checks are the first line. These tests prove the second line: the rule
still holds when the application is wrong, or when someone runs a fix-up statement by
hand at three in the morning during a cyclone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.domain.ids import uuid7
from tests.schema.factories import (
    append_chained,
    make_admin_hierarchy,
    make_entitlement,
    make_user_with_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _make_plan(db: AsyncConnection) -> str:
    plan_id = uuid7()
    await db.execute(
        text(
            "INSERT INTO incident.dispatch_plan "
            "(id, incident_ids, proposed_by_agent, status, correlation_id) "
            "VALUES (:id, ARRAY[:incident]::uuid[], 'triage-dispatch-agent', "
            " 'AWAITING_SIGNOFF', 'test')"
        ),
        {"id": plan_id, "incident": uuid7()},
    )
    return str(plan_id)


async def test_a_dispatch_plan_cannot_be_released_without_signoff(
    db: AsyncConnection,
) -> None:
    plan_id = await _make_plan(db)

    with pytest.raises(DBAPIError, match="without a recorded human sign-off"):
        await db.execute(
            text("UPDATE incident.dispatch_plan SET status = 'RELEASED' WHERE id = :id"),
            {"id": plan_id},
        )


async def test_a_dispatch_plan_cannot_be_completed_without_signoff(
    db: AsyncConnection,
) -> None:
    """COMPLETED is downstream of RELEASED; skipping straight to it is the same bypass."""
    plan_id = await _make_plan(db)

    with pytest.raises(DBAPIError, match="without a recorded human sign-off"):
        await db.execute(
            text("UPDATE incident.dispatch_plan SET status = 'COMPLETED' WHERE id = :id"),
            {"id": plan_id},
        )


async def test_a_signed_off_plan_may_be_released(db: AsyncConnection) -> None:
    plan_id = await _make_plan(db)
    approver = await make_user_with_role(db, "DISPATCHER", "LK-11")

    await db.execute(
        text(
            "UPDATE incident.dispatch_plan "
            "SET status = 'RELEASED', signed_off_by = :approver, signed_off_at = now() "
            "WHERE id = :id"
        ),
        {"id": plan_id, "approver": approver},
    )

    result = await db.execute(
        text("SELECT status FROM incident.dispatch_plan WHERE id = :id"), {"id": plan_id}
    )
    assert result.scalar_one() == "RELEASED"


async def test_a_recorded_signoff_cannot_be_reassigned(db: AsyncConnection) -> None:
    """Who approved a life-safety action is not an editable field."""
    plan_id = await _make_plan(db)
    first = await make_user_with_role(db, "DISPATCHER", "LK-11")
    second = await make_user_with_role(db, "DMC_OPERATOR", "LK")

    await db.execute(
        text(
            "UPDATE incident.dispatch_plan "
            "SET status = 'APPROVED', signed_off_by = :first, signed_off_at = now() "
            "WHERE id = :id"
        ),
        {"id": plan_id, "first": first},
    )

    with pytest.raises(DBAPIError, match="cannot be reassigned"):
        await db.execute(
            text("UPDATE incident.dispatch_plan SET signed_off_by = :second WHERE id = :id"),
            {"id": plan_id, "second": second},
        )


async def test_the_resting_state_is_also_constrained(db: AsyncConnection) -> None:
    """An INSERT straight into RELEASED bypasses the UPDATE trigger, so a CHECK covers it."""
    with pytest.raises(IntegrityError, match="released_requires_signoff"):
        await db.execute(
            text(
                "INSERT INTO incident.dispatch_plan "
                "(id, incident_ids, proposed_by_agent, status, correlation_id) "
                "VALUES (:id, ARRAY[:incident]::uuid[], 'agent', 'RELEASED', 'test')"
            ),
            {"id": uuid7(), "incident": uuid7()},
        )


async def _release(db: AsyncConnection, entitlement_id: object, released_by: object) -> None:
    """Release funds, supplying the chain fields as the service must."""
    await append_chained(
        db,
        schema="aid",
        table="disbursement",
        columns={
            "id": uuid7(),
            "entitlement_id": entitlement_id,
            "amount_lkr_cents": 100000000,
            "released_by": released_by,
            "payment_rail": "BANK_TRANSFER",
            "correlation_id": "test",
        },
    )


async def test_releasing_funds_requires_district_approver(db: AsyncConnection) -> None:
    """A GN officer may assess damage. They may not release money against it."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    gn_officer = await make_user_with_role(db, "GN_OFFICER", hierarchy["gn_code"])

    with pytest.raises(DBAPIError, match="may not release a disbursement"):
        await _release(db, entitlement["entitlement_id"], gn_officer)


async def test_a_district_approver_may_release_funds(db: AsyncConnection) -> None:
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])

    await _release(db, entitlement["entitlement_id"], approver)

    result = await db.execute(
        text("SELECT count(*) FROM aid.disbursement WHERE entitlement_id = :id"),
        {"id": entitlement["entitlement_id"]},
    )
    assert result.scalar_one() == 1


async def test_a_disbursement_has_no_unattributed_path(db: AsyncConnection) -> None:
    """Money never moves without a named person behind it.

    Two guards cover this and either is sufficient: the NOT NULL on `released_by`, and
    the authority trigger, which fires first and rejects a NULL releaser as holding no
    role. The assertion is that the write is refused, not which guard catches it.
    """
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)

    with pytest.raises(DBAPIError, match="may not release a disbursement"):
        await db.execute(
            text(
                "INSERT INTO aid.disbursement "
                "(id, entitlement_id, amount_lkr_cents, released_by, payment_rail, "
                " correlation_id) "
                "VALUES (:id, :entitlement_id, 100000000, NULL, 'BANK_TRANSFER', 'test')"
            ),
            {"id": uuid7(), "entitlement_id": entitlement["entitlement_id"]},
        )


async def test_a_released_disbursement_cannot_be_edited(db: AsyncConnection) -> None:
    """Corrections are new compensating entries, never edits."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])
    await _release(db, entitlement["entitlement_id"], approver)

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("UPDATE aid.disbursement SET amount_lkr_cents = 1"))


async def test_a_released_disbursement_cannot_be_deleted(db: AsyncConnection) -> None:
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])
    await _release(db, entitlement["entitlement_id"], approver)

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("DELETE FROM aid.disbursement"))
