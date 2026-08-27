"""Recomputing and verifying the audit hash chain.

The chain is written by the `public.sarana_hash_chain()` BEFORE INSERT trigger, which
hashes the canonical jsonb form of the row with `entry_hash` removed. Verification
recomputes with *the same expression, in the database*, rather than reimplementing the
canonicalisation in Python.

That is the whole design of this module. A Python reimplementation would have to
reproduce PostgreSQL's jsonb key ordering, numeric formatting and timestamp rendering
exactly, and the day it drifted, every entry would look tampered with - or worse, a real
tamper would verify clean because both sides made the same mistake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `to_jsonb(t) - 'entry_hash'` is exactly what the trigger hashes. Keep these two in step:
# if the trigger's payload expression ever changes, this must change with it.
_RECOMPUTE = "encode(sha256(convert_to((to_jsonb(t) - 'entry_hash')::text, 'UTF8')), 'hex')"

_VERIFY_SQL = f"""
SELECT t.seq,
       t.entry_hash,
       t.prev_hash,
       {_RECOMPUTE} AS recomputed_hash,
       LAG(t.entry_hash) OVER (ORDER BY t.seq) AS preceding_hash
FROM audit.audit_entry t
WHERE t.seq >= :from_seq AND t.seq <= :to_seq
ORDER BY t.seq
"""  # noqa: S608 - interpolates _RECOMPUTE, a module constant, not caller input

# The row immediately before the range, so a mid-chain verification can still check that
# its first row links to what actually precedes it.
_ANCHOR_SQL = """
SELECT entry_hash
FROM audit.audit_entry
WHERE seq < :from_seq
ORDER BY seq DESC
LIMIT 1
"""

_BOUNDS_SQL = """
SELECT COALESCE(MIN(seq), 0) AS min_seq, COALESCE(MAX(seq), 0) AS max_seq
FROM audit.audit_entry
"""


@dataclass(frozen=True, slots=True)
class Divergence:
    """The first place the chain stops adding up."""

    seq: int
    reason: str
    expected: str | None
    found: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "reason": self.reason,
            "expected": self.expected,
            "found": self.found,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What a verification pass found.

    `intact` is the answer an auditor wants; `divergence` is the first row that broke and
    why, because "something is wrong somewhere" is not an actionable finding.
    """

    intact: bool
    checked: int
    from_seq: int
    to_seq: int
    divergence: Divergence | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intact": self.intact,
            "checked": self.checked,
            "from_seq": self.from_seq,
            "to_seq": self.to_seq,
            "divergence": self.divergence.as_dict() if self.divergence else None,
        }


async def chain_bounds(session: AsyncSession) -> tuple[int, int]:
    """The lowest and highest sequence numbers present."""
    result = await session.execute(text(_BOUNDS_SQL))
    row = result.mappings().one()
    return int(row["min_seq"]), int(row["max_seq"])


async def verify_range(session: AsyncSession, *, from_seq: int, to_seq: int) -> VerificationResult:
    """Recompute the chain over a range and return the first divergence, if any.

    Two independent things are checked per row, because they fail differently:

      1. The row's own hash still matches its contents. A row edited in place fails here.
      2. The row's `prev_hash` matches the entry_hash of the row before it. A row deleted
         from the middle, or one spliced in, fails here while every individual hash still
         looks fine.
    """
    anchor_result = await session.execute(text(_ANCHOR_SQL), {"from_seq": from_seq})
    anchor = anchor_result.scalar_one_or_none()

    result = await session.execute(text(_VERIFY_SQL), {"from_seq": from_seq, "to_seq": to_seq})
    rows = list(result.mappings())

    checked = 0
    for index, row in enumerate(rows):
        checked += 1
        seq = int(row["seq"])

        if row["entry_hash"] != row["recomputed_hash"]:
            return VerificationResult(
                intact=False,
                checked=checked,
                from_seq=from_seq,
                to_seq=to_seq,
                divergence=Divergence(
                    seq=seq,
                    reason="entry_hash does not match the row contents",
                    expected=row["recomputed_hash"],
                    found=row["entry_hash"],
                ),
            )

        # For the first row of the range the predecessor came from the anchor query; for
        # the rest it is the previous row in this result set.
        expected_prev = anchor if index == 0 else rows[index - 1]["entry_hash"]
        if row["prev_hash"] != expected_prev:
            return VerificationResult(
                intact=False,
                checked=checked,
                from_seq=from_seq,
                to_seq=to_seq,
                divergence=Divergence(
                    seq=seq,
                    reason="prev_hash does not match the preceding entry",
                    expected=expected_prev,
                    found=row["prev_hash"],
                ),
            )

    return VerificationResult(intact=True, checked=checked, from_seq=from_seq, to_seq=to_seq)
