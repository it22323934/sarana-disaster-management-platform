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
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now


class ReversalRefused(ValueError):
    """The reversal cannot be recorded as asked.

    Always a refusal, never a partial write. A compensating entry that landed without its
    grievance would take the money back off the books and leave the household uninformed,
    which is worse than the failed payment it was correcting.
    """


class ReversalReason(StrEnum):
    """Why a rail returned money it had already accepted.

    Mirrors the CHECK on `aid.disbursement_reversal.reason` and the failure reasons
    `gov-mock`'s payment rail reports. `tests/ledger/test_vocabularies.py` asserts the
    three agree, because a value the schema rejects is a 500 at the exact moment a
    household's payment has just bounced.
    """

    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    ACCOUNT_DORMANT = "ACCOUNT_DORMANT"
    NAME_MISMATCH = "NAME_MISMATCH"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    RAIL_RETURNED = "RAIL_RETURNED"
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    ADMINISTRATIVE_ERROR = "ADMINISTRATIVE_ERROR"

    @property
    def needs_new_bank_details(self) -> bool:
        """Whether fixing this means the household supplying a different account.

        The distinction an officer needs first: these cases cannot be retried at all until
        somebody speaks to the household, while the others may resolve on a second attempt.
        """
        return self in {
            ReversalReason.ACCOUNT_CLOSED,
            ReversalReason.INVALID_ACCOUNT,
            ReversalReason.NAME_MISMATCH,
        }


# What the household is told, per reason, in all three languages. Non-negotiable #2: a
# citizen-facing string does not exist here in fewer than three. These are written as
# instructions rather than diagnoses - "take your bank book to the Divisional Secretariat"
# is actionable; "ACCOUNT_DORMANT" is not.
REASON_TEXT: Final[dict[ReversalReason, dict[str, str]]] = {
    ReversalReason.ACCOUNT_CLOSED: {
        "si": "ඔබගේ බැංකු ගිණුම වසා ඇති බැවින් ගෙවීම ආපසු ලැබුණි. නව ගිණුම් විස්තර සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "உங்கள் வங்கிக் கணக்கு மூடப்பட்டதால் பணம் திருப்பி அனுப்பப்பட்டது. புதிய "
        "கணக்கு விவரங்களுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the bank account is closed. Please take "
        "new account details to the Divisional Secretariat.",
    },
    ReversalReason.ACCOUNT_DORMANT: {
        "si": "ඔබගේ බැංකු ගිණුම නිෂ්ක්‍රීය බැවින් ගෙවීම ආපසු ලැබුණි. ගිණුම නැවත සක්‍රීය කිරීමට ඔබගේ බැංකු ශාඛාවට යන්න.",
        "ta": "உங்கள் வங்கிக் கணக்கு செயலிழந்துள்ளதால் பணம் திருப்பி அனுப்பப்பட்டது. "
        "கணக்கை மீண்டும் இயக்க உங்கள் வங்கிக் கிளைக்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the bank account is dormant. Please visit "
        "your bank branch to reactivate it.",
    },
    ReversalReason.NAME_MISMATCH: {
        "si": "බැංකු ගිණුමේ නම ලේඛනගත නමට නොගැලපෙන බැවින් ගෙවීම ආපසු ලැබුණි. "
        "හැඳුනුම්පත සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "வங்கிக் கணக்கின் பெயர் பதிவுப் பெயருடன் பொருந்தாததால் பணம் திருப்பி "
        "அனுப்பப்பட்டது. அடையாள அட்டையுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the account name does not match the "
        "registered name. Please take your identity card to the Divisional Secretariat.",
    },
    ReversalReason.INVALID_ACCOUNT: {
        "si": "බැංකු ගිණුම් අංකය වලංගු නොවේ. නිවැරදි විස්තර සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "வங்கிக் கணக்கு எண் செல்லுபடியாகாது. சரியான விவரங்களுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The bank account number is not valid. Please take the correct details to "
        "the Divisional Secretariat.",
    },
    ReversalReason.LIMIT_EXCEEDED: {
        "si": "ගිණුමේ සීමාව ඉක්මවා ගිය බැවින් ගෙවීම ආපසු ලැබුණි. එය නැවත යවනු ලැබේ; ඔබ කිසිවක් කළ යුතු නැත.",
        "ta": "கணக்கு வரம்பு மீறியதால் பணம் திருப்பி அனுப்பப்பட்டது. அது மீண்டும் "
        "அனுப்பப்படும்; நீங்கள் எதுவும் செய்யத் தேவையில்லை.",
        "en": "The payment was returned because an account limit was exceeded. It will be "
        "sent again; you do not need to do anything.",
    },
    ReversalReason.RAIL_RETURNED: {
        "si": "බැංකුව ගෙවීම ආපසු එවා ඇත. හේතුව සොයා බලමින් සිටී; ඔබට නැවත දැනුම් දෙනු ලැබේ.",
        "ta": "வங்கி பணத்தைத் திருப்பி அனுப்பியுள்ளது. காரணம் ஆராயப்படுகிறது; உங்களுக்கு மீண்டும் தெரிவிக்கப்படும்.",
        "en": "The bank returned the payment. The reason is being investigated and you "
        "will be contacted again.",
    },
    ReversalReason.DUPLICATE_PAYMENT: {
        "si": "මෙම ගෙවීම දෙවරක් යවා ඇති බැවින් එක් ගෙවීමක් ආපසු ගන්නා ලදී. ඔබට හිමි මුදල වෙනස් වී නැත.",
        "ta": "இந்தப் பணம் இரண்டு முறை அனுப்பப்பட்டதால் ஒன்று திரும்பப் பெறப்பட்டது. உங்களுக்கு உரிய தொகை மாறவில்லை.",
        "en": "This payment was sent twice, so one has been reversed. The amount you are "
        "owed has not changed.",
    },
    ReversalReason.ADMINISTRATIVE_ERROR: {
        "si": "පරිපාලන දෝෂයක් හේතුවෙන් ගෙවීම ආපසු ගන්නා ලදී. නිවැරදි කිරීමෙන් පසු ඔබට දැනුම් දෙනු ලැබේ.",
        "ta": "நிர்வாகப் பிழை காரணமாக பணம் திரும்பப் பெறப்பட்டது. திருத்தப்பட்ட பின் உங்களுக்குத் தெரிவிக்கப்படும்.",
        "en": "The payment was reversed because of an administrative error. You will be "
        "contacted once it is corrected.",
    },
}

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
