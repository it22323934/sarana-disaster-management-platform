"""The one definition of what a public ledger entry is.

Three things have to agree exactly or the transparency claim is false:

  1. what `repo.chain_writer` hashes when a disbursement is written,
  2. what `/api/v1/ledger/public` publishes,
  3. what `workers.anchor` builds the daily Merkle tree over.

If any two of those differ by a single field, an honest ledger fails verification and the
alarm is indistinguishable from tampering. So they all call `public_entry()`, and the shape
is defined here rather than three times.

**What the entry deliberately does not contain.** No household id, no NIC, no phone
number, no GN division, no coordinate, no assessment reference, and no name of any kind.
An `entitlement_id` is a UUID with no public resolver, and `released_by` is an officer's
user id - a UUID, not a name - which stays in because the ledger's whole purpose is to
commit to who released public money.

**Timestamps are strings, not datetimes.** `released_at` is rendered with `.isoformat()`
here so the hashed form and the published form are byte-identical. Leaving it as a datetime
would put the answer in the hands of whichever JSON serialiser ran, and `+00:00` versus `Z`
is enough to break every hash in the feed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

# Excluded when recomputing a hash. `prev_hash` and `entry_hash` because they are the
# output; `seq` and `anchor_date` because they are storage and grouping metadata that the
# entry's own chain linkage already orders. `tools/sarana-verify` excludes the same four.
NON_PAYLOAD_FIELDS: Final[tuple[str, ...]] = ("prev_hash", "entry_hash", "seq", "anchor_date")


def public_entry(
    *,
    entitlement_id: Any,
    amount_lkr_cents: int,
    released_by: Any,
    released_at: datetime | str,
    payment_rail: str,
    payment_ref: str | None,
) -> dict[str, Any]:
    """The canonical, hashable, publishable form of one disbursement.

    Field order is irrelevant - RFC 8785 sorts keys - but the field *set* is not, and this
    is the only place it is decided.
    """
    return {
        "entitlement_id": str(entitlement_id),
        "amount_lkr_cents": int(amount_lkr_cents),
        "released_by": str(released_by),
        "released_at": (released_at if isinstance(released_at, str) else released_at.isoformat()),
        "payment_rail": payment_rail,
        "payment_ref": payment_ref,
    }


def payload_of(row: dict[str, Any]) -> dict[str, Any]:
    """Strip a stored or published row back to the fields the hash covers."""
    return {key: value for key, value in row.items() if key not in NON_PAYLOAD_FIELDS}
