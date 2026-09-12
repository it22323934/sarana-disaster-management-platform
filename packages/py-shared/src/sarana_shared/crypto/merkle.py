"""Merkle trees for the daily ledger anchor.

Every day the ledger's entries for that day are reduced to one root hash, written to
object storage under a compliance-mode lock and published. Anyone can recompute the root
from the public feed; if it differs, something was changed after the fact.

**The odd-node rule is duplicate-last.** With an odd number of nodes at a level, the last
one is paired with itself. This is documented here and tested because it is the single
detail that most often differs between implementations - a verifier that promotes the odd
node instead of duplicating it computes a different root from identical data, and the
resulting alarm looks exactly like tampering.

Duplicate-last has a known weakness: without the count, two different trees can produce
the same root. The anchor record therefore always carries `entry_count`, `first_seq` and
`last_seq`, so a verifier checks the shape as well as the root.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sarana_shared.crypto.canonical import canonical_bytes
from sarana_shared.crypto.chain import HASH_FIELDS

EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


def leaf_hash(entry: Any) -> str:
    """The hash of one ledger entry, over its canonical form.

    Strips the same four fields the chain hash excludes - the two hashes, `seq` and
    `anchor_date` - so a leaf built here and a leaf recomputed by `tools/sarana-verify`
    from the published feed are the same bytes. Doing it inside this function rather than
    asking callers to strip first is deliberate: `build_anchor` needs `seq` to record the
    range it covers, so a caller that had already removed it could not, and one that had
    not would hash a different shape from the public.
    """
    if isinstance(entry, dict):
        entry = {key: value for key, value in entry.items() if key not in HASH_FIELDS}
    return hashlib.sha256(canonical_bytes(entry)).hexdigest()


def _pair_hash(left: str, right: str) -> str:
    """Combine two child hashes.

    Concatenates the hex digests rather than the raw bytes. Slower, and deliberate: it is
    what a verifier written in an afternoon with a shell script and `sha256sum` will do,
    and the point of publishing this is that it can be checked with ordinary tools.
    """
    return hashlib.sha256((left + right).encode("ascii")).hexdigest()


def merkle_root(leaves: list[str]) -> str:
    """The root of a tree over pre-hashed leaves.

    An empty day has a defined root rather than an error: days with no disbursements
    happen, and they still get an anchor so a gap in the published series always means
    something is missing.
    """
    if not leaves:
        return EMPTY_ROOT

    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            # Duplicate-last. See the module docstring.
            level.append(level[-1])
        level = [_pair_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass(frozen=True, slots=True)
class Anchor:
    """One day's published commitment to the ledger.

    Carries the shape as well as the root. A root alone is not enough to detect a removed
    entry, because duplicate-last lets a shorter tree collide with a longer one.
    """

    date: str
    merkle_root: str
    entry_count: int
    first_seq: int
    last_seq: int
    prev_anchor_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "merkle_root": self.merkle_root,
            "entry_count": self.entry_count,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "prev_anchor_hash": self.prev_anchor_hash,
        }

    def anchor_hash(self) -> str:
        """This anchor's own hash, which the next day references.

        Chaining the anchors as well as the entries means removing a whole day is as
        detectable as altering one row inside it.
        """
        return hashlib.sha256(canonical_bytes(self.as_dict())).hexdigest()


def build_anchor(
    entries: list[dict[str, Any]],
    *,
    date: str,
    prev_anchor_hash: str | None = None,
) -> Anchor:
    """Reduce a day's entries to one anchor.

    Entries are hashed in the order given, which must be `seq` order: a Merkle root is
    order-dependent, so a verifier reading the public feed sorted differently would get a
    different root from identical data.
    """
    leaves = [leaf_hash(entry) for entry in entries]
    sequences = [int(entry["seq"]) for entry in entries] if entries else [0]

    return Anchor(
        date=date,
        merkle_root=merkle_root(leaves),
        entry_count=len(entries),
        first_seq=min(sequences),
        last_seq=max(sequences),
        prev_anchor_hash=prev_anchor_hash,
    )


def verify_anchor(entries: list[dict[str, Any]], anchor: Anchor) -> str | None:
    """Recompute an anchor and describe the first disagreement, or None.

    Returns a sentence rather than a boolean because the answer a journalist needs is
    "what changed", not "something changed".
    """
    if len(entries) != anchor.entry_count:
        return (
            f"entry count differs: the anchor commits to {anchor.entry_count} entries, "
            f"the published feed has {len(entries)}"
        )

    recomputed = merkle_root([leaf_hash(entry) for entry in entries])
    if recomputed != anchor.merkle_root:
        return (
            f"merkle root differs for {anchor.date}: anchored {anchor.merkle_root}, "
            f"recomputed {recomputed}"
        )

    if entries:
        sequences = [int(entry["seq"]) for entry in entries]
        if min(sequences) != anchor.first_seq or max(sequences) != anchor.last_seq:
            return (
                f"sequence range differs: anchored {anchor.first_seq}..{anchor.last_seq}, "
                f"published {min(sequences)}..{max(sequences)}"
            )

    return None
