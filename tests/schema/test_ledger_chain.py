"""The aid ledger hash chain and its append-only guarantee.

ADR-005: a hash chain inside a database you control proves nothing on its own - the
operator can recompute the whole chain after tampering. These tests cover what the chain
does give: an append cannot claim a predecessor it does not have, and no entry can be
edited or removed in place. The external anchor is what closes the remaining hole, and it
is verified separately against the published Merkle roots.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.crypto.chain import chain_hash
from sarana_shared.db.sql import GENESIS_HASH
from sarana_shared.domain.ids import uuid7
from tests.schema.factories import (
    append_chained,
    make_admin_hierarchy,
    make_entitlement,
    make_user_with_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _approve(
    db: AsyncConnection, entitlement_id: object, level: str, approver: object
) -> None:
    """Record one approval, supplying the chain fields as the service must."""
    await append_chained(
        db,
        schema="aid",
        table="approval",
        columns={
            "id": uuid7(),
            "entitlement_id": entitlement_id,
            "level": level,
            "approver_id": approver,
            "decision": "APPROVED",
        },
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

    # A second, different approver: segregation of duty fires before the chain check, so
    # reusing the first one would prove nothing about the chain.
    district = await make_user_with_role(db, "DISTRICT_APPROVER", hierarchy["district_code"])

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
                "approver": district,
                "forged": "f" * 64,
            },
        )


async def test_the_entry_hash_is_reproducible_by_a_third_party(
    db: AsyncConnection,
) -> None:
    """An auditor with the row and the previous hash must reach the same digest.

    This is the property the public verifier depends on, and it is the one this test
    previously got wrong: it recomputed PostgreSQL's own `jsonb` text form, which is only
    reproducible by somebody running PostgreSQL. Key order and whitespace both differ from
    RFC 8785, so every published entry would have failed `sarana-verify`.

    The hash is now computed by the application with RFC 8785, and this checks it the way
    an outsider would.
    """
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", hierarchy["ds_code"])
    await _approve(db, entitlement["entitlement_id"], "DS", approver)

    result = await db.execute(
        text(
            "SELECT id, entitlement_id, level, approver_id, decision, prev_hash, entry_hash "
            "FROM aid.approval ORDER BY seq LIMIT 1"
        )
    )
    row = dict(result.mappings().one())

    payload = {
        key: str(value)
        for key, value in row.items()
        if key not in {"id", "prev_hash", "entry_hash"}
    }
    recomputed = chain_hash(payload, row["prev_hash"])

    assert recomputed == row["entry_hash"]


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

    # Appended with valid chain fields so the CHECK is what refuses it. A BEFORE INSERT
    # trigger fires ahead of a CHECK constraint, so omitting them here would prove only
    # that the chain trigger works - which is a different test.
    with pytest.raises(DBAPIError, match="refusal_has_a_reason"):
        await append_chained(
            db,
            schema="aid",
            table="approval",
            columns={
                "id": uuid7(),
                "entitlement_id": entitlement["entitlement_id"],
                "level": "DS",
                "approver_id": approver,
                "decision": "REJECTED",
            },
        )
