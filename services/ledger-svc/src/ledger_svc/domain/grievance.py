"""Grievances, and the confirmation reply that raises most of them.

ADR-008: any household may dispute any assessment, entitlement or disbursement affecting
it. This module owns what that means in practice - who may raise one, when the clock
starts, what blocks a payment, and how a one-word SMS becomes a case.

**The "NO" reply is the primary input, not an afterthought.** After every release the
household gets an SMS naming the amount and asking them to reply YES or NO. A NO costs the
sender one message and tells the platform something no dashboard can: that the money did
not arrive. It is the cheapest and highest-signal fraud and error detector in the system,
so it creates a grievance automatically rather than landing in a queue somebody may read.

**No reply is not evidence of non-receipt.** Someone whose phone is dead, or who never
received the SMS in the first place, has told us nothing. Those are recorded as
`unconfirmed`, never as `failed`, and the public figures report them as their own number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

import structlog

from ledger_svc.repo.base import GRIEVANCE_CHANNELS, GRIEVANCE_STATUSES, GRIEVANCE_SUBJECTS
from sarana_shared.domain.ids import short_code, uuid7
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

# Default SLA. Fourteen days is long enough to investigate a disputed assessment and short
# enough that a household is not left guessing through a whole recovery period.
DEFAULT_SLA_DAYS: Final = 14

# A disputed payment is the urgent kind: the household says money they were told about did
# not arrive, and every day of that is a day they are going without it.
SLA_DAYS_BY_SUBJECT: Final[dict[str, int]] = {
    "ASSESSMENT": 14,
    "ENTITLEMENT": 14,
    "DISBURSEMENT": 7,
}

# How long a household has to answer the confirmation SMS before one reminder, then
# `unconfirmed`. Seven days from the brief.
CONFIRMATION_WINDOW_DAYS: Final = 7

# Statuses in which a grievance still blocks its own entitlement's release. RESOLVED and
# REJECTED are dispositioned; ESCALATED is not - it has been passed upward, not answered.
OPEN_STATUSES: Final[frozenset[str]] = frozenset(
    {"RECEIVED", "ACKNOWLEDGED", "UNDER_REVIEW", "ESCALATED"}
)


class GrievanceRefused(ValueError):
    """The grievance cannot be raised or moved as asked."""


class ConfirmationReply(StrEnum):
    """What a household said when asked whether the money arrived."""

    YES = "YES"
    NO = "NO"
    UNRECOGNISED = "UNRECOGNISED"


# What counts as yes and no, in all three languages plus the obvious variants. A citizen
# replying to a life-or-death message must not have their answer discarded because they
# typed "ok" instead of "YES".
_YES_WORDS: Final[frozenset[str]] = frozenset(
    {"yes", "y", "ok", "okay", "ඔව්", "ඔව", "ஆம்", "சரி", "1"}
)
_NO_WORDS: Final[frozenset[str]] = frozenset({"no", "n", "not", "නැත", "නෑ", "இல்லை", "இல்ல", "2"})


def parse_confirmation(body: str) -> ConfirmationReply:
    """Read a household's reply.

    Unrecognised is a real answer and is never treated as either one. Guessing YES would
    close a case nobody confirmed; guessing NO would raise a grievance nobody filed. An
    unrecognised reply goes to a human, which is the only honest handling.
    """
    cleaned = body.strip().lower().strip(".!,")

    if cleaned in _YES_WORDS:
        return ConfirmationReply.YES
    if cleaned in _NO_WORDS:
        return ConfirmationReply.NO

    # A reply containing one of the words among others - "no it did not come" - still
    # counts, because that is how people actually answer.
    words = set(cleaned.split())
    if words & _NO_WORDS:
        return ConfirmationReply.NO
    if words & _YES_WORDS:
        return ConfirmationReply.YES

    return ConfirmationReply.UNRECOGNISED


def sla_due(raised_at: datetime, subject_type: str) -> datetime:
    """When this grievance must be answered by."""
    days = SLA_DAYS_BY_SUBJECT.get(subject_type, DEFAULT_SLA_DAYS)
    return raised_at + timedelta(days=days)


def public_ref(now: datetime | None = None) -> str:
    """`GRV-260828-K3M9PQ` - what the household is told to quote.

    Same shape and alphabet as an incident reference: read aloud over a phone, written on
    paper, and free of the characters people mishear.
    """
    return short_code("GRV", at=now or utc_now())


@dataclass(frozen=True, slots=True)
class NewGrievance:
    """A grievance ready to be stored."""

    public_ref: str
    household_id: UUID
    subject_type: str
    subject_id: UUID | None
    channel: str
    description: dict[str, str]
    raised_at: datetime
    sla_due_at: datetime
    status: str = "RECEIVED"
    assigned_ds_division_id: UUID | None = None
    assigned_ds_division_code: str | None = None
    correlation_id: str = ""

    def as_columns(self, *, grievance_id: UUID | None = None) -> dict[str, Any]:
        """Every column `aid.grievance` needs, JSON already serialised.

        `description` is dumped here rather than by the caller because the CHECK on the
        column requires a non-blank si, ta and en, and a caller that hands the driver a
        Python dict gets a type error from asyncpg instead of that constraint message.
        """
        return {
            "id": grievance_id or uuid7(),
            "public_ref": self.public_ref,
            "household_id": self.household_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "channel": self.channel,
            "description": json.dumps(self.description, ensure_ascii=False),
            "raised_at": self.raised_at,
            "sla_due_at": self.sla_due_at,
            "status": self.status,
            "assigned_ds_division_id": self.assigned_ds_division_id,
            "assigned_ds_division_code": self.assigned_ds_division_code,
            "correlation_id": self.correlation_id,
        }


def raise_grievance(
    *,
    household_id: UUID,
    subject_type: str,
    subject_id: UUID | None,
    channel: str,
    description: dict[str, str],
    raised_at: datetime | None = None,
    assigned_ds_division_id: UUID | None = None,
    assigned_ds_division_code: str | None = None,
    correlation_id: str = "",
) -> NewGrievance:
    """Build a grievance.

    Raises:
        GrievanceRefused: for a channel, subject or description the schema will not store.
            Refused here so the citizen's client gets a usable message rather than a
            constraint violation.
    """
    if channel not in GRIEVANCE_CHANNELS:
        raise GrievanceRefused(
            f"{channel!r} is not a channel a grievance can arrive on; expected one of "
            f"{', '.join(sorted(GRIEVANCE_CHANNELS))}"
        )
    if subject_type not in GRIEVANCE_SUBJECTS:
        raise GrievanceRefused(
            f"{subject_type!r} is not something a household can dispute; expected one of "
            f"{', '.join(sorted(GRIEVANCE_SUBJECTS))}"
        )
    if not description or not any((value or "").strip() for value in description.values()):
        raise GrievanceRefused(
            "a grievance must say what is wrong; an empty complaint cannot be investigated"
        )

    when = raised_at or utc_now()
    return NewGrievance(
        public_ref=public_ref(when),
        household_id=household_id,
        subject_type=subject_type,
        subject_id=subject_id,
        channel=channel,
        description=description,
        raised_at=when,
        sla_due_at=sla_due(when, subject_type),
        assigned_ds_division_id=assigned_ds_division_id,
        assigned_ds_division_code=assigned_ds_division_code,
        correlation_id=correlation_id,
    )


def from_confirmation_reply(
    *,
    household_id: UUID,
    disbursement_id: UUID,
    body: str,
    raised_at: datetime | None = None,
    assigned_ds_division_code: str | None = None,
    correlation_id: str = "",
) -> NewGrievance | None:
    """Turn a "NO" reply into a grievance, or return None.

    Returns None for YES and for anything unrecognised. An unrecognised reply is handled
    by a person rather than guessed at: raising a grievance nobody filed would waste an
    officer's day and put a false dispute on a household's record.
    """
    reply = parse_confirmation(body)
    if reply is not ConfirmationReply.NO:
        return None

    _log.info(
        "grievance_from_confirmation_reply",
        disbursement_id=str(disbursement_id),
        household_id=str(household_id),
    )
    return raise_grievance(
        household_id=household_id,
        subject_type="DISBURSEMENT",
        subject_id=disbursement_id,
        channel="SMS",
        # Recorded in all three languages because the household will be written back to,
        # and the reply must reach them in the language they used.
        description={
            "si": "ගෙවීම ලැබී නොමැති බව නිවැසියා දැනුම් දුන්නේය.",
            "ta": "பணம் கிடைக்கவில்லை என்று வீட்டார் தெரிவித்தனர்.",
            "en": "The household replied NO to the payment confirmation message.",
        },
        raised_at=raised_at,
        assigned_ds_division_code=assigned_ds_division_code,
        correlation_id=correlation_id,
    )


def blocks_release(status: str) -> bool:
    """Whether a grievance in this status stops its own entitlement being released.

    ESCALATED still blocks. It has been passed upward, not answered, and paying an amount
    while the dispute about it is still travelling would settle the question in one
    direction without anybody deciding it.
    """
    return status in OPEN_STATUSES


def assert_transition(current: str, requested: str) -> None:
    """Allow a status change, or refuse it.

    Deliberately permissive between the open states - an officer may acknowledge, review,
    and escalate in any order that reflects what actually happened. What is not allowed is
    reopening a dispositioned grievance, because that would let a resolution be quietly
    withdrawn.
    """
    if requested not in GRIEVANCE_STATUSES:
        raise GrievanceRefused(f"{requested!r} is not a grievance status")

    if current in {"RESOLVED", "REJECTED"}:
        raise GrievanceRefused(
            f"grievance is already {current} and cannot be reopened. Raise a new one, so "
            "the household keeps both the original answer and the new complaint."
        )


def assert_resolution_is_trilingual(resolution: dict[str, str]) -> None:
    """A resolution is sent to the citizen, so it exists in all three languages.

    Raises:
        GrievanceRefused: naming the missing locales.
    """
    missing = [
        locale for locale in ("si", "ta", "en") if not (resolution.get(locale) or "").strip()
    ]
    if missing:
        raise GrievanceRefused(
            f"a grievance resolution is sent to the household and must be written in all "
            f"three languages; missing or blank: {', '.join(missing)}"
        )


@dataclass(frozen=True, slots=True)
class ConfirmationOutcome:
    """What the confirmation loop concluded about one disbursement."""

    disbursement_id: UUID
    confirmed: bool
    unconfirmed: bool
    grievance: NewGrievance | None = None

    @property
    def summary(self) -> str:
        if self.confirmed:
            return "the household confirmed receipt"
        if self.grievance is not None:
            return "the household said the money did not arrive; a grievance was raised"
        return "no reply within the window; recorded as unconfirmed, not as failed"


def lapse_unconfirmed(
    *, disbursement_id: UUID, released_at: datetime, now: datetime | None = None
) -> ConfirmationOutcome | None:
    """Mark a disbursement unconfirmed once its window has passed.

    Returns None while the window is still open. `unconfirmed` is deliberately not
    `failed`: silence from a household means their phone is off, or the SMS never arrived,
    or they did not understand it. None of those is evidence the money is missing, and
    reporting them as failures would overstate a problem while hiding a different one.
    """
    moment = now or utc_now()
    if moment - released_at < timedelta(days=CONFIRMATION_WINDOW_DAYS):
        return None

    return ConfirmationOutcome(disbursement_id=disbursement_id, confirmed=False, unconfirmed=True)
