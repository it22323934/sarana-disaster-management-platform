"""The aid ledger hash chain and its append-only guarantee.

ADR-005: a hash chain inside a database you control proves nothing on its own - the
operator can recompute the whole chain after tampering. These tests cover what the chain
does give: an append cannot claim a predecessor it does not have, and no entry can be
edited or removed in place. The external anchor is what closes the remaining hole, and it
is verified separately against the published Merkle roots.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.db.sql import GENESIS_HASH
from sarana_shared.domain.ids import uuid7
from tests.schema.factories import make_admin_hierarchy, make_entitlement, make_user_with_role

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _approve(
    db: AsyncConnection, entitlement_id: object, level: str, approver: object
) -> None:
    await db.execute(
        text(
            "INSERT INTO aid.approval "
            "(id, entitlement_id, level, approver_id, decision) "
            "VALUES (:id, :entitlement_id, :level, :approver, 'APPROVED')"
        ),
        {"id": uuid7(), "entitlement_id": entitlement_id, "level": level, "approver": approver},
    )


async def test_the_first_entry_links_to_the_genesis_hash(db: AsyncConnection) -> None:
    """Every chain starts from a fixed, publicly known value rather than NULL.

    A verifier then checks the first entry exactly the way it checks every other one.
    """
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])

    await _approve(db, entitlement["entitlement_id"], "DS", approver)

    result = await db.execute(
        text("SELECT prev_hash, entry_hash FROM aid.approval ORDER BY seq LIMIT 1")
    )
    prev_hash, entry_hash = result.one()

    assert prev_hash == GENESIS_HASH
    assert len(entry_hash) == 64


async def test_each_entry_links_to_the_one_before_it(db: AsyncConnection) -> None:
    hierarchy = await make_admin_hierarchy(db)
    first = await make_entitlement(db, hierarchy)
    second = await make_entitlement(db, hierarchy)
    ds = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])
    district = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])

    await _approve(db, first["entitlement_id"], "DS", ds)
    await _approve(db, second["entitlement_id"], "DISTRICT", district)

    result = await db.execute(text("SELECT prev_hash, entry_hash FROM aid.approval ORDER BY seq"))
    rows = result.all()

    assert len(rows) == 2
    assert rows[1].prev_hash == rows[0].entry_hash


async def test_an_entry_claiming_the_wrong_predecessor_is_refused(
    db: AsyncConnection,
) -> None:
    """The tamper case: an insert that tries to fork the chain."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])
    await _approve(db, entitlement["entitlement_id"], "DS", approver)

    with pytest.raises(DBAPIError, match="hash chain break"):
        await db.execute(
            text(
                "INSERT INTO aid.approval "
                "(id, entitlement_id, level, approver_id, decision, prev_hash) "
                "VALUES (:id, :entitlement_id, 'DISTRICT', :approver, 'APPROVED', :forged)"
            ),
            {
                "id": uuid7(),
                "entitlement_id": entitlement["entitlement_id"],
                "approver": approver,
                "forged": "f" * 64,
            },
        )


async def test_the_entry_hash_is_reproducible_by_a_third_party(
    db: AsyncConnection,
) -> None:
    """An auditor with the row and the previous hash must reach the same digest.

    This is the property the public verifier depends on: the hash is over the row's
    canonical JSON form, and jsonb sorts its keys, so nothing about the computation
    depends on privileged access or on our code.
    """
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])
    await _approve(db, entitlement["entitlement_id"], "DS", approver)

    result = await db.execute(
        text(
            "SELECT (to_jsonb(a) - 'entry_hash')::text AS payload, entry_hash "
            "FROM aid.approval a ORDER BY seq LIMIT 1"
        )
    )
    payload, entry_hash = result.one()

    recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    assert recomputed == entry_hash


async def test_an_approval_cannot_be_edited(db: AsyncConnection) -> None:
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])
    await _approve(db, entitlement["entitlement_id"], "DS", approver)

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("UPDATE aid.approval SET decision = 'REJECTED'"))


async def test_a_refusal_must_give_a_reason(db: AsyncConnection) -> None:
    """A household cannot contest a decision it was given no grounds for."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])

    with pytest.raises(DBAPIError, match="refusal_has_a_reason"):
        await db.execute(
            text(
                "INSERT INTO aid.approval "
                "(id, entitlement_id, level, approver_id, decision) "
                "VALUES (:id, :entitlement_id, 'DS', :approver, 'REJECTED')"
            ),
            {"id": uuid7(), "entitlement_id": entitlement["entitlement_id"], "approver": approver},
        )
