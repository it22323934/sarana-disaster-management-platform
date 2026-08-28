"""The database and the published verifier agree about the hash chain.

This is the test that would have caught the defect it exists because of. The ledger's
claim is that anyone can recompute the numbers; before this, entries written by the
database hashed one way and `sarana-verify` recomputed them another, so every published
entry would have failed verification.

Two ends have to meet:

  - the **application** computes `entry_hash` with `sarana_shared.crypto.chain`, which is
    RFC 8785 - the same scheme `tools/sarana-verify` uses;
  - the **database** refuses any entry whose `prev_hash` does not match the tail, and any
    entry with no hash at all.

Neither alone is sufficient. Without the first, nobody outside can verify; without the
second, any writer could fork the chain.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.crypto.chain import GENESIS_HASH, chain_hash, link, verify_link
from sarana_shared.domain.ids import uuid7

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "tools" / "sarana-verify") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools" / "sarana-verify"))

import verify  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --------------------------------------------------------------------------------------
# The two implementations are the same implementation
# --------------------------------------------------------------------------------------


def test_the_shared_hasher_and_the_verifier_agree() -> None:
    """The verifier is what the public runs; the shared module is what writes.

    If these ever diverge, every published entry silently stops verifying - which is
    exactly the defect this file was written after finding.
    """
    entry: dict[str, Any] = {
        "seq": 7,
        "amount_lkr_cents": 47_500_00,
        "entitlement_id": str(uuid7()),
        "payment_rail": "BANK_TRANSFER",
        "prev_hash": GENESIS_HASH,
    }

    assert chain_hash(entry) == verify.entry_hash(entry)


def test_both_use_the_same_genesis_value() -> None:
    assert GENESIS_HASH == verify.GENESIS_HASH


def test_both_exclude_the_same_fields_from_the_payload() -> None:
    from sarana_shared.crypto.chain import HASH_FIELDS

    assert set(HASH_FIELDS) == set(verify.HASH_FIELDS)


def test_a_chain_built_by_the_application_verifies_end_to_end() -> None:
    """Build a chain the way the service will, then check it the way the public will."""
    entries: list[dict[str, Any]] = []
    previous = GENESIS_HASH

    for index in range(1, 6):
        entries.append(
            link(
                {
                    "seq": index,
                    "anchor_date": "2026-08-28",
                    "amount_lkr_cents": 10_000_00 * index,
                    "entitlement_id": f"01a04400-0000-7000-8000-{index:012d}",
                },
                previous,
            )
        )
        previous = entries[-1]["entry_hash"]

    assert verify.verify_chain(entries) is None


def test_link_does_not_mutate_its_argument() -> None:
    """A caller holding a record whose hash no longer describes it is the quiet bug."""
    original = {"seq": 1, "amount_lkr_cents": 100}

    link(original)

    assert "entry_hash" not in original


def test_verify_link_distinguishes_an_edit_from_a_removal() -> None:
    """Different investigations, so they must be different answers."""
    entry = link({"seq": 1, "amount_lkr_cents": 100})

    edited = dict(entry)
    edited["amount_lkr_cents"] = 999
    assert "altered" in (verify_link(edited) or "")

    assert "removed or inserted" in (verify_link(entry, "deadbeef" * 8) or "")


def test_an_untouched_entry_verifies() -> None:
    assert verify_link(link({"seq": 1, "amount_lkr_cents": 100})) is None


# --------------------------------------------------------------------------------------
# The database enforces the chain without computing it
# --------------------------------------------------------------------------------------


async def _entitlement(db: AsyncConnection) -> Any:
    """A minimal entitlement for a disbursement to reference."""
    result = await db.execute(text("SELECT id FROM aid.entitlement LIMIT 1"))
    existing = result.scalar_one_or_none()
    return existing


async def test_the_database_refuses_a_disbursement_with_no_hash(db: AsyncConnection) -> None:
    """A hash nobody can reproduce is worse than none: it looks verifiable and is not.

    So an entry arriving without one is refused rather than given a locally-computed hash.
    """
    entitlement_id = await _entitlement(db)
    if entitlement_id is None:
        pytest.skip("no entitlement in the test database to attach a disbursement to")

    with pytest.raises(Exception, match="entry_hash must be supplied"):
        await db.execute(
            text(
                "INSERT INTO aid.disbursement "
                "(id, entitlement_id, amount_lkr_cents, released_by, payment_rail, "
                " correlation_id) "
                "VALUES (:id, :ent, 1000, :by, 'BANK_TRANSFER', :corr)"
            ),
            {"id": uuid7(), "ent": entitlement_id, "by": uuid7(), "corr": str(uuid7())},
        )


async def test_the_database_refuses_a_prev_hash_that_does_not_match_the_tail(
    db: AsyncConnection,
) -> None:
    """The property only the database can guarantee.

    An application cannot see the true tail under concurrency; the advisory lock and this
    check are what stop two writers forking the chain.
    """
    entitlement_id = await _entitlement(db)
    if entitlement_id is None:
        pytest.skip("no entitlement in the test database to attach a disbursement to")

    payload = {"seq": 1, "amount_lkr_cents": 1000}

    with pytest.raises(Exception, match="hash chain break"):
        await db.execute(
            text(
                "INSERT INTO aid.disbursement "
                "(id, entitlement_id, amount_lkr_cents, released_by, payment_rail, "
                " correlation_id, prev_hash, entry_hash) "
                "VALUES (:id, :ent, 1000, :by, 'BANK_TRANSFER', :corr, :prev, :hash)"
            ),
            {
                "id": uuid7(),
                "ent": entitlement_id,
                "by": uuid7(),
                "corr": str(uuid7()),
                # Deliberately not the current tail.
                "prev": "ab" * 32,
                "hash": chain_hash(payload, "ab" * 32),
            },
        )


async def test_the_trigger_no_longer_computes_the_hash_itself(db: AsyncConnection) -> None:
    """The change this migration made.

    The old trigger silently overwrote whatever the application supplied with its own
    PostgreSQL-jsonb hash, which is what made published entries unverifiable.
    """
    result = await db.execute(
        text(
            "SELECT p.proname FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'aid' AND c.relname = 'disbursement' "
            "  AND t.tgname = 'hash_chain'"
        )
    )
    function_name = result.scalar_one_or_none()

    assert function_name == "sarana_enforce_supplied_chain"


async def test_the_audit_chain_deliberately_keeps_the_trigger_computed_scheme(
    db: AsyncConnection,
) -> None:
    """Not an oversight - a decision, asserted so it stays a decision.

    `audit.audit_entry` is verified internally by core-api's `/audit/verify`, which
    recomputes with the same SQL expression. The two agree with each other, it is never
    published for outside verification, and changing it would mean changing that verifier
    in lockstep for no gain.
    """
    result = await db.execute(
        text(
            "SELECT p.proname FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'audit' AND c.relname = 'audit_entry' "
            "  AND t.tgname = 'hash_chain'"
        )
    )

    assert result.scalar_one_or_none() == "sarana_hash_chain"
