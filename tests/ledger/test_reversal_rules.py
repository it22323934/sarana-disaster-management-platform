"""The reversal rules, without a database.

Pure domain: no session, no clock beyond the one it is handed, no container. Split from
`test_reversal.py` because those tests are about triggers and a partial unique index and
have to run against the real schema, while these are about what the code will and will not
agree to do — and a rule that needs Postgres to be checked is a rule in the wrong place.
"""

from __future__ import annotations

import pytest

from ledger_svc.domain import reversal as domain
from sarana_shared.domain.ids import uuid7

AMOUNT = 250_000_00


def test_a_machine_cannot_record_a_human_judgement() -> None:
    """A worker may report what a bank returned, not decide a payment was a mistake.

    A system that can decide by itself that a disbursement was an administrative error can
    take money back off the books with nobody accountable for the decision.
    """
    with pytest.raises(domain.ReversalRefused, match="judgement"):
        domain.reverse(
            disbursement_id=uuid7(),
            entitlement_id=uuid7(),
            amount_lkr_cents=AMOUNT,
            reason="ADMINISTRATIVE_ERROR",
            by_machine=True,
        )


def test_a_person_may_record_an_administrative_error() -> None:
    """The same reason, from a human, is allowed."""
    entry = domain.reverse(
        disbursement_id=uuid7(),
        entitlement_id=uuid7(),
        amount_lkr_cents=AMOUNT,
        reason="ADMINISTRATIVE_ERROR",
        by_machine=False,
    )
    assert entry.reason is domain.ReversalReason.ADMINISTRATIVE_ERROR


def test_an_unknown_reason_is_refused() -> None:
    """Refused in the domain, so the caller gets a usable message.

    A value the schema rejects would otherwise be a constraint violation surfacing as a
    500 at the exact moment a household's payment has just bounced.
    """
    with pytest.raises(domain.ReversalRefused, match="not a reason"):
        domain.reverse(
            disbursement_id=uuid7(),
            entitlement_id=uuid7(),
            amount_lkr_cents=AMOUNT,
            reason="BECAUSE",
        )


def test_a_reversal_must_name_a_positive_amount() -> None:
    """A zero reversal would mark the payment failed with no money accounted for."""
    with pytest.raises(domain.ReversalRefused, match="positive"):
        domain.reverse(
            disbursement_id=uuid7(),
            entitlement_id=uuid7(),
            amount_lkr_cents=0,
            reason="ACCOUNT_CLOSED",
        )


def test_every_reason_tells_the_household_something_in_three_languages() -> None:
    """Non-negotiable #2, on the path where it is easiest to forget.

    This text goes into a grievance and then to a household. A reason with only English
    would reach a Tamil-speaking family as nothing at all.
    """
    for reason in domain.ReversalReason:
        text_for = domain.REASON_TEXT[reason]
        assert set(text_for) == {"si", "ta", "en"}, f"{reason.value} is missing a language"
        for locale, value in text_for.items():
            assert value.strip(), f"{reason.value} is blank in {locale}"


def test_every_reason_says_what_to_do_rather_than_what_went_wrong() -> None:
    """The English text is an instruction, not a diagnosis.

    "ACCOUNT_DORMANT" tells a family nothing. "Visit your bank branch to reactivate it"
    tells them what to do on Monday morning.
    """
    for reason in domain.ReversalReason:
        english = domain.REASON_TEXT[reason]["en"]
        assert reason.value not in english, (
            f"{reason.value} shows the household an enum value instead of an instruction"
        )
        assert len(english) > 40, f"{reason.value} is too terse to act on"


def test_the_reasons_a_machine_may_report_are_things_a_bank_says() -> None:
    """`MACHINE_REPORTABLE` holds observations, never judgements."""
    assert domain.ReversalReason.ADMINISTRATIVE_ERROR not in domain.MACHINE_REPORTABLE
    assert domain.ReversalReason.DUPLICATE_PAYMENT not in domain.MACHINE_REPORTABLE
    assert domain.ReversalReason.ACCOUNT_CLOSED in domain.MACHINE_REPORTABLE
