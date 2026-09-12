"""The two messages a household gets about their money.

Both go to one person about their own payment, which makes them different from an alert in
two ways that matter.

**They are not subject to the review gate.** An alert template is drafted, reviewed in
three languages by named people, and published before it can be dispatched, because it goes
to a district and a mistake reaches everybody at once. These go to one household about a
fact the ledger already recorded, and holding a payment confirmation behind a human
sign-off would mean nobody ever gets one.

**They carry an amount.** So the numbers are formatted here, once, in the way a Sri Lankan
reader expects — and the reference is included, because "did you get 47,500 rupees?" is
answerable and "did you get your relief payment?" is not.

Trilingual, like everything citizen-facing. The household's own `preferred_language` picks
one; there is no English fallback, because the whole point of the field is that somebody
recorded which language this family reads.

The confirmation message asks for a reply. That reply is the highest-signal input the
platform gets — it is the only independent evidence that money actually arrived — so the
instruction has to be unmissable and the words have to be ones a phone keyboard can produce
in any of the three languages. YES and NO, in Latin characters, in all three.
"""

from __future__ import annotations

from typing import Final

# The reply words, in Latin characters in every language. A Sinhala or Tamil keyboard can
# type these; asking somebody to switch input methods to answer a one-word question is
# asking them not to answer.
YES: Final = "YES"
NO: Final = "NO"


def format_lkr(amount_lkr_cents: int) -> str:
    """Render an amount the way a reader expects: `47,500` rather than `4750000`.

    Cents are dropped, not rounded down by accident: every entitlement in the schedule is a
    whole number of rupees, so a non-zero cents part would itself be the bug worth seeing.
    """
    return f"{amount_lkr_cents // 100:,}"


def confirmation_message(*, amount_lkr_cents: int, payment_ref: str | None, language: str) -> str:
    """Ask a household whether the money arrived.

    Sent after every release. The reply creates a grievance automatically if it is NO,
    which is why the instruction is the last line rather than buried: a message whose
    ask is in the middle gets read as a notification.
    """
    amount = format_lkr(amount_lkr_cents)
    reference = payment_ref or "-"
    return _CONFIRMATION[_pick(language)].format(amount=amount, reference=reference)


def reversal_message(
    *, amount_lkr_cents: int, reason_text: str, grievance_ref: str, language: str
) -> str:
    """Tell a household their payment came back, and what happens next.

    `reason_text` comes from `ledger_svc.domain.reversal.REASON_TEXT` and is already in
    this household's language — it is written as an instruction rather than a diagnosis, so
    it is dropped in whole rather than summarised.

    The grievance reference is included because a case has already been opened on their
    behalf. Without it the household has been told something went wrong and given no way to
    ask about it.
    """
    amount = format_lkr(amount_lkr_cents)
    return _REVERSAL[_pick(language)].format(
        amount=amount, reason=reason_text, reference=grievance_ref
    )


def _pick(language: str) -> str:
    """Which language to render in.

    Falls back to English only for a value that is not one of the three. That is a data
    error rather than a preference, and the alternative - refusing to send - would mean a
    household receives nothing because a column holds a typo.
    """
    return language if language in _CONFIRMATION else "en"


_CONFIRMATION: Final[dict[str, str]] = {
    "si": (
        "සරණ: රු. {amount} ක ආපදා සහන ගෙවීමක් ඔබගේ ගිණුමට යවා ඇත. "
        "යොමු අංකය: {reference}. "
        "මුදල ලැබුණේ නම් YES ලෙසත්, නොලැබුණේ නම් NO ලෙසත් පිළිතුරු දෙන්න."
    ),
    "ta": (
        "சரண: ரூ. {amount} பேரிடர் நிவாரணத் தொகை உங்கள் கணக்கிற்கு அனுப்பப்பட்டுள்ளது. "
        "குறிப்பு எண்: {reference}. "
        "பணம் கிடைத்தால் YES என்றும், கிடைக்கவில்லை என்றால் NO என்றும் பதிலளிக்கவும்."
    ),
    "en": (
        "SARANA: LKR {amount} in disaster relief has been sent to your account. "
        "Reference: {reference}. "
        "Reply YES if it arrived, or NO if it did not."
    ),
}

_REVERSAL: Final[dict[str, str]] = {
    "si": (
        "සරණ: රු. {amount} ක ගෙවීම ඔබගේ ගිණුමට බැර නොවී ආපසු ලැබුණි. {reason} "
        "ඔබ වෙනුවෙන් පැමිණිල්ලක් විවෘත කර ඇත. යොමු අංකය: {reference}."
    ),
    "ta": (
        "சரண: ரூ. {amount} தொகை உங்கள் கணக்கில் சேராமல் திருப்பி வந்துள்ளது. {reason} "
        "உங்கள் சார்பாக ஒரு முறையீடு திறக்கப்பட்டுள்ளது. குறிப்பு எண்: {reference}."
    ),
    "en": (
        "SARANA: the LKR {amount} payment did not reach your account and has been "
        "returned. {reason} A case has been opened for you. Reference: {reference}."
    ),
}
