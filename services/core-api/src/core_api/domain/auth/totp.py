"""TOTP enrolment, verification, and the step-up window.

Every officer account carries a second factor. For the two mandatory human gates it is
not enough to have used it at login: committing a dispatch or releasing money requires a
fresh code, verified within the last five minutes.

The reason is narrow and specific. An unattended workstation with a live session is the
realistic attack on a disaster response platform - not a stolen password. Step-up means
the person authorising the payment is at the keyboard at the moment of authorising it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import pyotp

from sarana_shared.domain.time import utc_now

ISSUER: Final = "SARANA"

DIGITS: Final = 6
PERIOD_SECONDS: Final = 30

# One period either side, to tolerate clock drift on a field device that has not synced
# in days. Wider than this starts to matter: each extra window multiplies the number of
# codes an attacker can guess at once.
VALID_WINDOW: Final = 1

# How long a verified second factor authorises a gated action for.
STEP_UP_WINDOW: Final = timedelta(minutes=5)

# Recovery codes for a lost device. A GN officer whose phone is destroyed in the disaster
# they are responding to must not be locked out of recording assessments.
RECOVERY_CODE_COUNT: Final = 10
RECOVERY_CODE_BYTES: Final = 5


class InvalidTOTP(ValueError):
    """The submitted code did not verify."""


@dataclass(frozen=True, slots=True)
class Enrolment:
    """A newly generated second factor, before the user has confirmed it."""

    secret: str
    provisioning_uri: str
    recovery_codes: tuple[str, ...]


def enrol(account_name: str) -> Enrolment:
    """Generate a secret, its QR provisioning URI, and a set of recovery codes.

    The secret is not active until `confirm_enrolment` verifies a code from it. Activating
    on generation would let a mistyped scan lock someone out of their own account.
    """
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD_SECONDS).provisioning_uri(
        name=account_name, issuer_name=ISSUER
    )
    codes = tuple(
        secrets.token_hex(RECOVERY_CODE_BYTES).upper() for _ in range(RECOVERY_CODE_COUNT)
    )
    return Enrolment(secret=secret, provisioning_uri=uri, recovery_codes=codes)


def verify(secret: str, code: str, *, at: datetime | None = None) -> bool:
    """Check a submitted code against a secret.

    Returns False rather than raising, so the caller decides whether a miss is a failed
    login, a failed step-up, or a failed enrolment confirmation - three things that need
    different audit entries and different lockout treatment.
    """
    if not code or not code.strip().isdigit():
        return False
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD_SECONDS)
    return bool(totp.verify(code.strip(), for_time=at or utc_now(), valid_window=VALID_WINDOW))


def confirm_enrolment(secret: str, code: str, *, at: datetime | None = None) -> None:
    """Activate an enrolment by proving the user can produce a code from it.

    Raises:
        InvalidTOTP: if the code does not verify. The secret stays inactive.
    """
    if not verify(secret, code, at=at):
        raise InvalidTOTP(
            "That code did not match. Check the time on your device and try the next code."
        )


def step_up_expires_at(verified_at: datetime) -> datetime:
    """When a step-up verification stops authorising gated actions."""
    return verified_at + STEP_UP_WINDOW


def is_step_up_fresh(verified_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether a second factor verified at `verified_at` is still inside the window."""
    if verified_at is None:
        return False
    return (now or utc_now()) - verified_at <= STEP_UP_WINDOW
