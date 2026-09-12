"""The published hash chain for the aid ledger.

    entry_hash = SHA256( canonical_json(entry without its hashes) || prev_hash )

`canonical_json` is RFC 8785. This is the scheme `tools/sarana-verify` recomputes and the
one build file 10 specifies, so it is the scheme the application must use when it writes.

**Why the application computes this and the database does not.** The `sarana_hash_chain()`
trigger from build file 04 hashes PostgreSQL's own `jsonb` text form, which differs from
RFC 8785 in three ways that each break verification on their own:

    key order    postgres sorts by (length, bytes); RFC 8785 by UTF-16 code unit
                     postgres:  {"z": 1, "aa": 2}
                     RFC 8785:  {"aa":2,"z":1}
    whitespace   postgres emits `{"a": 2}`; RFC 8785 emits `{"a":2}`
    prev_hash    postgres folds it into the payload; the scheme appends it

Implementing RFC 8785 in plpgsql would be a great deal of error-prone SQL to reproduce a
standard that already has a tested implementation two directories away. So the split is:

  - the **application** computes the hash, here, with the canonicaliser the verifier uses;
  - the **database** enforces what only it can - that `prev_hash` matches the current tail,
    that a hash was supplied, and that nothing is ever updated or deleted.

The property that matters is unchanged: no writer can break the chain, because the
database refuses a row whose `prev_hash` does not match. What changes is that the hash is
now the published, independently reproducible one.

`audit.audit_entry` deliberately keeps the original trigger-computed scheme. That chain is
verified internally by core-api's `/audit/verify`, which recomputes with the same SQL
expression, so the two agree with each other. It is never published for outside
verification, so it does not need RFC 8785 - and changing it would mean changing the
verifier in lockstep for no gain.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from sarana_shared.crypto.canonical import canonical_bytes

# The value the first entry in a chain builds on. Matches `sarana_hash_chain()`'s genesis
# so a chain started under either scheme begins the same way.
GENESIS_HASH: Final = "0" * 64

# Excluded from the hashed payload.
#
# The two hashes, because they are the output. `prev_hash` is appended after the canonical
# form rather than folded into it, so the chaining is visible in the algorithm rather than
# buried in the data.
#
# `seq` and `anchor_date`, because they are storage and grouping metadata rather than
# content. `seq` is a database identity column that is not known until the row is written,
# so an entry could not be hashed before it was inserted if the hash covered it; the chain
# linkage already fixes the order, which is the property `seq` would otherwise supply.
# `anchor_date` is derived from `released_at` by a timezone conversion, so committing to it
# would make the hash depend on a rendering rather than on a fact.
#
# `reversed` joined them in file 11's follow-up. It is a later fact *about* the entry - a
# bank returned the money - recorded authoritatively as its own hashed row in
# aid.disbursement_reversal. The disbursement still means "this was released, on this date,
# by this person", and that stays true. A ledger whose entry hash changed when a payment
# bounced would fail verification for an honest reason, which is the worst kind.
#
# `tools/sarana-verify` excludes exactly these five, and `tests/ledger/test_chain_agreement`
# asserts the two lists are the same set. That test exists because they diverged once.
HASH_FIELDS: Final[tuple[str, ...]] = (
    "prev_hash",
    "entry_hash",
    "seq",
    "anchor_date",
    "reversed",
)

# The two fields `link()` recomputes and writes back. Distinct from HASH_FIELDS on purpose:
# that one says what the hash does not cover, this one says what the record does not keep
# from its input. Conflating them made `link()` drop `seq` from the entry it returned.
OUTPUT_FIELDS: Final[tuple[str, ...]] = ("prev_hash", "entry_hash")


def chain_hash(entry: dict[str, Any], prev_hash: str | None = None) -> str:
    """The entry's hash under the published scheme.

    `prev_hash` may be passed explicitly or carried on the entry. Absent both, the entry
    is treated as the head of the chain and builds on the genesis value.
    """
    previous = prev_hash or entry.get("prev_hash") or GENESIS_HASH
    payload = {key: value for key, value in entry.items() if key not in HASH_FIELDS}
    return hashlib.sha256(canonical_bytes(payload) + previous.encode("ascii")).hexdigest()


def link(entry: dict[str, Any], prev_hash: str | None = None) -> dict[str, Any]:
    """Return the entry with `prev_hash` and `entry_hash` filled in.

    Does not mutate its argument: a caller that hashed an entry and then edited it would
    otherwise be holding a record whose hash silently no longer describes it.
    """
    previous = prev_hash or entry.get("prev_hash") or GENESIS_HASH
    linked = {key: value for key, value in entry.items() if key not in OUTPUT_FIELDS}
    linked["prev_hash"] = previous
    linked["entry_hash"] = chain_hash(linked, previous)
    return linked


def verify_link(entry: dict[str, Any], prev_hash: str | None = None) -> str | None:
    """Check one entry, returning what is wrong or None.

    A sentence rather than a boolean: an auditor needs to know whether the row was edited
    or whether one before it was removed, and those are different investigations.
    """
    expected_previous = prev_hash if prev_hash is not None else entry.get("prev_hash")
    declared = entry.get("prev_hash") or GENESIS_HASH

    if expected_previous is not None and declared != (expected_previous or GENESIS_HASH):
        return (
            "prev_hash does not match the preceding entry - an entry may have been "
            "removed or inserted"
        )

    recomputed = chain_hash(entry, declared)
    if recomputed != entry.get("entry_hash"):
        return "entry_hash does not match the entry's contents - this row has been altered"

    return None
