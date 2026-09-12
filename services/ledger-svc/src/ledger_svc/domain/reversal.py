"""Compensating entries: what a ledger does when a released payment turns out to fail.

About three transfers in a hundred fail *after* the rail accepted them. By then
`aid.disbursement` has recorded a release, hashed it, and published it. The table is
append-only and must stay that way — an auditor has to be able to see that the state
believed it had paid this household, and when.

So the correction is an entry, not an edit. Four things happen together, and all four or
none:

  1. a compensating entry is appended to `aid.disbursement_reversal`, on its own hash
     chain, committing to the disbursement it reverses;
  2. `aid.disbursement.reversed_at` is stamped by a database trigger, so the back-pointer
     cannot drift from the entry;
  3. a grievance is raised **on the household's behalf**, because nobody told them;
  4. the entitlement returns to `APPROVED`, so the money they are owed can be sent again.

**Never a silent retry.** Re-sending to the same account that just rejected it produces a
second failure and a household still waiting, with the ledger now claiming two payments. A
retry is a new release through the human gate, after somebody has looked at why the first
one bounced.

**The reason is not decoration.** Each one has a different remedy — a closed account needs
new bank details, a name mismatch needs the register checked, a dormant account needs the
household to visit a branch. It is carried into the grievance in all three languages so the
officer who picks the case up knows what to ask for, and the household is told something
they can act on rather than "payment failed".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.reversal_reasons import REASON_TEXT as _REASON_TEXT
from sarana_shared.domain.reversal_reasons import ReversalReason as _ReversalReason
from sarana_shared.domain.time import utc_now


class ReversalRefused(ValueError):
    """The reversal cannot be recorded as asked.

    Always a refusal, never a partial write. A compensating entry that landed without its
    grievance would take the money back off the books and leave the household uninformed,
    which is worse than the failed payment it was correcting.
    """


# The reason vocabulary and the trilingual text a household is shown both live in
# `sarana_shared.domain.reversal_reasons`, because three services need the same answer and
# none may import another's code: gov-mock's rail reports the reason, this service stores it
# and puts the text in a grievance, and alerting-svc renders it into the SMS.
#
# Re-exported here so the ledger's own callers keep reading `domain.reversal`.
ReversalReason = _ReversalReason
REASON_TEXT = _REASON_TEXT


# Reasons a machine may record on its own. The rail reports these and they are facts about
# a transfer, so a worker may write them without a human in the loop.
#
# `ADMINISTRATIVE_ERROR` and `DUPLICATE_PAYMENT` are deliberately absent: they are
# judgements about what somebody did, not observations of what a bank returned, and a
# system that can decide by itself that a payment was a mistake can take money back off the
# books without anyone deciding to.
MACHINE_REPORTABLE: Final[frozenset[ReversalReason]] = frozenset(
    {
        ReversalReason.ACCOUNT_CLOSED,
        ReversalReason.ACCOUNT_DORMANT,
        ReversalReason.NAME_MISMATCH,
        ReversalReason.INVALID_ACCOUNT,
        ReversalReason.LIMIT_EXCEEDED,
        ReversalReason.RAIL_RETURNED,
    }
)

# Excluded when recomputing a reversal's hash, for the same reasons the disbursement
# excludes its four: `prev_hash`/`entry_hash` are the output, `seq` is an identity column
# not known before insertion, and `anchor_date` is a rendering. `grievance_id` joins them
# because which case number was opened is operational metadata rather than part of what the
# correction says happened - the substance is the amount, the reason and the payment it
# reverses, and all three are hashed.
NON_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "prev_hash",
    "entry_hash",
    "seq",
    "anchor_date",
    "grievance_id",
)


def public_reversal(
    *,
    disbursement_id: Any,
    entitlement_id: Any,
    amount_lkr_cents: int,
    reason: str,
    rail_reference: str | None,
    reversed_at: datetime | str,
) -> dict[str, Any]:
    """The canonical, hashable, publishable form of one compensating entry.

    `disbursement_id` is inside the payload on purpose: the hash commits to *which* payment
    was reversed, so a reversal cannot later be denied or quietly re-pointed at a different
    one. That is the whole difference between a compensating entry and a note in a file.

    `reversed_at` is rendered to a string here, exactly as `ledger_entry.public_entry` does,
    so the hashed form and the published form are byte-identical. `+00:00` versus `Z` from
    a JSON serialiser is enough to break every hash in the feed, and it would break at
    deployment rather than in a test.
    """
    return {
        "disbursement_id": str(disbursement_id),
        "entitlement_id": str(entitlement_id),
        "amount_lkr_cents": int(amount_lkr_cents),
        "reason": str(reason),
        "rail_reference": rail_reference,
        "reversed_at": (reversed_at if isinstance(reversed_at, str) else reversed_at.isoformat()),
    }


def payload_of(row: dict[str, Any]) -> dict[str, Any]:
    """Strip a stored or published reversal back to the fields the hash covers."""
    return {key: value for key, value in row.items() if key not in NON_PAYLOAD_FIELDS}


@dataclass(frozen=True, slots=True)
class Reversal:
    """A compensating entry, ready to be written."""

    id: UUID
    disbursement_id: UUID
    entitlement_id: UUID
    amount_lkr_cents: int
    reason: ReversalReason
    rail_reference: str | None
    reversed_at: datetime
    correlation_id: str

    def as_columns(self, *, grievance_id: UUID) -> dict[str, Any]:
        """Every column `aid.disbursement_reversal` needs, apart from the two hashes.

        `grievance_id` is passed in rather than held on the entry because the case is
        opened first: the table is append-only, so a reversal has to be complete when it
        lands or its case number could never be attached at all.
        """
        return {
            "id": self.id,
            "grievance_id": grievance_id,
            "disbursement_id": self.disbursement_id,
            "entitlement_id": self.entitlement_id,
            "amount_lkr_cents": self.amount_lkr_cents,
            "reason": self.reason.value,
            "rail_reference": self.rail_reference,
            "reversed_at": self.reversed_at,
            "correlation_id": self.correlation_id,
        }

    def hashed_payload(self) -> dict[str, Any]:
        """What the chain covers. One definition, shared with the feed and the anchor."""
        return public_reversal(
            disbursement_id=self.disbursement_id,
            entitlement_id=self.entitlement_id,
            amount_lkr_cents=self.amount_lkr_cents,
            reason=self.reason.value,
            rail_reference=self.rail_reference,
            reversed_at=self.reversed_at,
        )

    def grievance_description(self) -> dict[str, str]:
        """What the household is told, in all three languages."""
        return dict(REASON_TEXT[self.reason])


def reverse(
    *,
    disbursement_id: UUID,
    entitlement_id: UUID,
    amount_lkr_cents: int,
    reason: str,
    rail_reference: str | None = None,
    reversed_at: datetime | None = None,
    correlation_id: str = "",
    by_machine: bool = False,
) -> Reversal:
    """Build a compensating entry.

    Pure: no I/O, no clock unless one is withheld, no randomness beyond the id. The same
    inputs produce the same hashed payload forever, which is what lets an auditor recompute
    it years later.

    Raises:
        ReversalRefused: for a reason the schema will not store, a non-positive amount, or
            a machine trying to record a reason that is a human judgement.
    """
    try:
        parsed = ReversalReason(reason)
    except ValueError as error:
        raise ReversalRefused(
            f"{reason!r} is not a reason a payment can be reversed for; expected one of "
            f"{', '.join(sorted(item.value for item in ReversalReason))}"
        ) from error

    if amount_lkr_cents <= 0:
        # The reversal carries the amount coming back, as a positive number. A zero or
        # negative reversal would net to nothing and leave the disbursement marked reversed
        # with no money accounted for.
        raise ReversalRefused(
            "a reversal must name the amount coming back, as a positive number of cents"
        )

    if by_machine and parsed not in MACHINE_REPORTABLE:
        raise ReversalRefused(
            f"{parsed.value} is a judgement about what somebody did, not something a rail "
            "reports. A worker may not record it; a person must."
        )

    return Reversal(
        id=uuid7(),
        disbursement_id=disbursement_id,
        entitlement_id=entitlement_id,
        amount_lkr_cents=amount_lkr_cents,
        reason=parsed,
        rail_reference=rail_reference,
        reversed_at=reversed_at or utc_now(),
        correlation_id=correlation_id,
    )
