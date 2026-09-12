"""One-time codes for citizens.

Citizens have no password. The phone number is the identity and a six-digit code is the
proof, which is the only scheme that works for someone reporting a collapsed house from a
borrowed handset with no email address and no app installed.

The message goes out in the household's preferred language first. A Tamil-speaking family
in Batticaloa receiving a Sinhala-only verification code is the same failure as the
Sinhala-and-English-only press conference on 28 November 2025, in miniature and at scale.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sarana_shared.domain.localised import Locale, LocalisedText
from sarana_shared.domain.time import utc_now

DIGITS: Final = 6

TTL: Final = timedelta(minutes=5)

MAX_ATTEMPTS: Final = 3

# Sends per number per hour. Three is enough for a genuine retry after a failed delivery
# and few enough that the platform cannot be used to bombard someone's phone.
MAX_SENDS_PER_HOUR: Final = 3

SEND_WINDOW: Final = timedelta(hours=1)


class OTPExhausted(Exception):
    """The code has been attempted too many times, or has expired."""


class OTPRateLimited(Exception):
    """Too many codes requested for this number in the window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"Too many verification codes requested. Try again in "
            f"{max(1, retry_after_seconds // 60)} minute(s)."
        )
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class GeneratedOTP:
    """A freshly minted code and when it stops being accepted."""

    code: str
    expires_at: datetime


def generate(*, now: datetime | None = None) -> GeneratedOTP:
    """Mint a six-digit code.

    `secrets.randbelow` rather than `random`: the module that seeds from the clock is
    exactly the wrong one for a credential, and the mistake is invisible in testing.
    Leading zeros are preserved - a code is a string, not a number.
    """
    code = f"{secrets.randbelow(10**DIGITS):0{DIGITS}d}"
    return GeneratedOTP(code=code, expires_at=(now or utc_now()) + TTL)


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """Whether a challenge has passed its five-minute window."""
    return (now or utc_now()) >= expires_at


def attempts_remaining(attempts: int, max_attempts: int = MAX_ATTEMPTS) -> int:
    """How many tries are left before the challenge is burnt."""
    return max(0, max_attempts - attempts)


def assert_can_send(recent_send_times: list[datetime], *, now: datetime | None = None) -> None:
    """Refuse a send that would exceed the per-number hourly limit.

    Raises:
        OTPRateLimited: carrying the seconds until the oldest send falls out of the
            window, so the caller can tell the citizen when to try again rather than
            leaving them tapping a dead button.
    """
    moment = now or utc_now()
    in_window = [sent for sent in recent_send_times if moment - sent < SEND_WINDOW]
    if len(in_window) < MAX_SENDS_PER_HOUR:
        return

    oldest = min(in_window)
    retry_after = int((oldest + SEND_WINDOW - moment).total_seconds())
    raise OTPRateLimited(max(1, retry_after))


# Pre-translated and native-speaker reviewed, like every alert template. Never machine
# translated at send time. `{code}` is the only substitution.
MESSAGE_TEMPLATE: Final = LocalisedText(
    si="ඔබගේ SARANA සත්‍යාපන කේතය {code} වේ. එය මිනිත්තු 5කින් කල් ඉකුත් වේ. එය කිසිවකු සමඟ බෙදා නොගන්න.",
    ta="உங்கள் SARANA சரிபார்ப்புக் குறியீடு {code}. இது 5 நிமிடங்களில் காலாவதியாகும். இதை யாருடனும் பகிர வேண்டாம்.",
    en="Your SARANA verification code is {code}. It expires in 5 minutes. "
    "Do not share it with anyone.",
)


def render_message(code: str, locale: Locale) -> str:
    """Render the code in one language, for the SMS body."""
    return MESSAGE_TEMPLATE.get(locale).format(code=code)


def render_all_locales(code: str) -> LocalisedText:
    """Render the code in all three, for the delivery record and for a fallback send."""
    return LocalisedText(
        si=MESSAGE_TEMPLATE.si.format(code=code),
        ta=MESSAGE_TEMPLATE.ta.format(code=code),
        en=MESSAGE_TEMPLATE.en.format(code=code),
    )
