"""Password hashing with Argon2id.

Parameters are tuned so a single verification costs roughly 250ms on the deployment
target. That is deliberately slow: it is the difference between an attacker with a leaked
hash table testing billions of candidates and testing thousands.

Argon2id rather than bcrypt or PBKDF2 because it is memory-hard, which is what makes GPU
and ASIC attacks expensive rather than merely parallel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.profiles import RFC_9106_LOW_MEMORY

_log = structlog.get_logger(__name__)

# Memory and parallelism come from RFC 9106's low-memory profile: 64 MiB, 4 lanes. The
# high-memory profile wants 2 GiB per hash, which on a Fargate task sized for this service
# would let a handful of concurrent logins exhaust the container - low-memory is the RFC's
# own recommendation for exactly that constraint.
MEMORY_COST: Final = RFC_9106_LOW_MEMORY.memory_cost
PARALLELISM: Final = RFC_9106_LOW_MEMORY.parallelism
HASH_LENGTH: Final = 32
SALT_LENGTH: Final = 16

# Passes over memory. The profile's default of 3 costs roughly 90ms on current hardware;
# the target is ~250ms, slow enough that a leaked hash table is expensive to attack and
# fast enough that a GN officer signing in on a bad connection does not notice it.
#
# This number is hardware-specific and will drift as machines get faster, so it is
# calibrated rather than guessed: 8 passes measures ~250ms median on the current
# development hardware. `test_password.py` asserts the cost stays inside 120-700ms - a
# floor that catches silent weakening, and a ceiling that catches a login path slow
# enough to become its own denial of service.
TIME_COST: Final = 8

TARGET_HASH_MS: Final = 250

# Below this a password is trivially guessable whatever the hash costs.
MIN_PASSWORD_LENGTH: Final = 12


class WeakPassword(ValueError):
    """The password does not meet the minimum policy."""


@dataclass(frozen=True, slots=True)
class PasswordHasherService:
    """Hashes and verifies passwords, and reports when a hash needs upgrading."""

    hasher: PasswordHasher

    @classmethod
    def create(cls) -> PasswordHasherService:
        """Build a hasher with the tuned parameters."""
        return cls(
            hasher=PasswordHasher(
                time_cost=TIME_COST,
                memory_cost=MEMORY_COST,
                parallelism=PARALLELISM,
                hash_len=HASH_LENGTH,
                salt_len=SALT_LENGTH,
            )
        )

    def hash(self, password: str) -> str:
        """Hash a password after checking it against the minimum policy.

        Raises:
            WeakPassword: if the password is shorter than the minimum.
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise WeakPassword(f"a password must be at least {MIN_PASSWORD_LENGTH} characters")
        return self.hasher.hash(password)

    def verify(self, stored_hash: str | None, password: str) -> bool:
        """Check a password against its stored hash.

        A missing hash still runs a verification against a dummy value. Returning early
        would make "this account has no password" measurable from the response time,
        which tells an attacker which accounts are worth attacking.
        """
        target = stored_hash or _DUMMY_HASH
        try:
            self.hasher.verify(target, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        return stored_hash is not None

    def needs_rehash(self, stored_hash: str) -> bool:
        """Whether the stored hash was made with weaker parameters than the current ones.

        Checked on every successful login, so a parameter increase upgrades accounts as
        people sign in rather than needing a migration nobody will run.
        """
        try:
            return self.hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return True


# Built once at import: hashing a throwaway value on every failed login would cost the
# same 250ms again and turn the timing defence into a denial-of-service lever.
_DUMMY_HASH: Final = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST,
    parallelism=PARALLELISM,
    hash_len=HASH_LENGTH,
    salt_len=SALT_LENGTH,
).hash("sarana-timing-equaliser")


def measure_hash_cost_ms(service: PasswordHasherService) -> float:
    """Time one hash, so the tuning can be asserted rather than assumed."""
    started = time.perf_counter()
    service.hash("a-representative-passphrase")
    return (time.perf_counter() - started) * 1000
