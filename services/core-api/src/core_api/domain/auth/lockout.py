"""Failed-login backoff, per account and per source address.

Exponential, capped at fifteen minutes, and never permanent. That cap is a safety
decision, not a security compromise: a GN officer locked out of the platform during a
cyclone cannot record damage, cannot receive dispatch, and cannot be reached by the
system that is supposed to be coordinating the response. A permanent lock turns a
password problem into a life-safety problem.

Fifteen minutes is enough to make online guessing useless - roughly four attempts an hour
against a 12-character minimum - while leaving a locked-out officer a way back in the
same shift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sarana_shared.domain.time import utc_now

# The first few attempts are free: fat fingers on a phone keyboard in the rain are not
# an attack, and locking on the second miss would generate more support load than it
# prevents intrusions.
FREE_ATTEMPTS: Final = 3

BASE_DELAY: Final = timedelta(seconds=5)

MAX_DELAY: Final = timedelta(minutes=15)

# Attempts older than this stop counting, so yesterday's typos do not compound today.
ATTEMPT_WINDOW: Final = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class LockoutState:
    """The current backoff for one account or one address."""

    failed_attempts: int
    locked_until: datetime | None

    @property
    def is_locked(self) -> bool:
        """Whether an attempt right now would be refused."""
        return self.locked_until is not None and self.locked_until > utc_now()

    def retry_after_seconds(self, *, now: datetime | None = None) -> int:
        """Seconds until the next attempt is allowed. Zero when not locked."""
        if self.locked_until is None:
            return 0
        remaining = self.locked_until - (now or utc_now())
        return max(0, int(remaining.total_seconds()))


def delay_for(failed_attempts: int) -> timedelta:
    """The backoff after `failed_attempts` consecutive failures.

    Doubles per attempt beyond the free ones, capped. Computed rather than stored, so
    the policy lives in one place and changing it does not need a data migration.
    """
    if failed_attempts <= FREE_ATTEMPTS:
        return timedelta(0)

    excess = failed_attempts - FREE_ATTEMPTS
    # 2**excess grows fast; cap the exponent before it overflows into an absurd timedelta.
    scaled: timedelta = BASE_DELAY * (2 ** min(excess - 1, 16))
    return scaled if scaled < MAX_DELAY else MAX_DELAY


def next_lock_until(failed_attempts: int, *, now: datetime | None = None) -> datetime | None:
    """When the account unlocks after this many failures, or None if it is not locked."""
    delay = delay_for(failed_attempts)
    if delay == timedelta(0):
        return None
    return (now or utc_now()) + delay


def is_within_window(attempted_at: datetime, *, now: datetime | None = None) -> bool:
    """Whether a past attempt is recent enough to still count toward the backoff."""
    return (now or utc_now()) - attempted_at <= ATTEMPT_WINDOW
