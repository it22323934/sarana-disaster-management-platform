"""Deriving an outcome from an identifier, stably and evenly.

Several mocks decide something once and must keep deciding it the same way forever: whether
a transfer fails, whether the CMS returns a claim, whether a NIC is on the register. None
of these may be *drawn*, because a transfer that fails on one poll and settles on the next
is a mock nobody can debug against — and because a household told two different things
about the same card is far worse than a consistent gap.

So the outcome is derived from the identifier. The subtlety is in how.

**A checksum over the characters does not work.** It looks fine and it clusters badly.
`sum(ord(c) for c in ref) % 1000` over `SARANA-PAY-0000` through `SARANA-PAY-0499` spans
about twenty consecutive values, because the fixed prefix contributes a constant and four
digits cannot vary the total by much. The result is not "3% of transfers fail" but "3% of
reference *namespaces* fail" — a whole batch either all fails or all succeeds, and which
one you get depends on the prefix somebody chose. That bug shipped here once and was caught
by a test that could not find a single failing reference in five hundred tries.

A cryptographic digest has no such structure: one changed character moves the bucket
anywhere. It is used here for its distribution, not for any security property, and the
`salt` keeps independent decisions about the same identifier independent — a NIC's presence
on the register must not correlate with whether that household's payment fails.
"""

from __future__ import annotations

import hashlib
from typing import Final

# Enough of the digest to be far larger than any bucket count used here, and cheap.
_DIGEST_BYTES: Final = 8


def bucket(value: str, *, buckets: int, salt: str) -> int:
    """Map an identifier to `[0, buckets)`, stably and evenly.

    Stable across processes, restarts and Python versions — unlike `hash()`, which is
    randomised per process and would make every mock's decisions change on restart.

    Raises:
        ValueError: if `buckets` is not positive. A zero bucket count is a caller bug and
            silently returning 0 would make every identifier share one outcome.
    """
    if buckets <= 0:
        raise ValueError(f"buckets must be positive, got {buckets}")
    digest = hashlib.sha256(f"{salt}:{value}".encode()).digest()
    return int.from_bytes(digest[:_DIGEST_BYTES], "big") % buckets


def falls_within(value: str, *, share: float, salt: str, precision: int = 10_000) -> bool:
    """Whether an identifier falls in the given share of the population.

    `share` is a fraction: 0.03 means about three in a hundred. The precision is the number
    of buckets, so a share as small as one in ten thousand is still representable rather
    than rounding to never.
    """
    if not 0.0 <= share <= 1.0:
        raise ValueError(f"share must be between 0 and 1, got {share}")
    return bucket(value, buckets=precision, salt=salt) < share * precision


def choose[T](value: str, options: tuple[T, ...], *, salt: str) -> T:
    """Pick one option for an identifier, stably.

    Raises:
        ValueError: if `options` is empty.
    """
    if not options:
        raise ValueError("cannot choose from an empty tuple of options")
    return options[bucket(value, buckets=len(options), salt=salt)]


def seed_for(*parts: str | int) -> int:
    """A stable seed for `random.Random`, from any mix of identifiers.

    Every synthetic series in the mocks is documented as a pure function of its inputs -
    "the same simulated hour produces the same reading on every machine and every replay".
    Seeding from `hash()` breaks that claim silently: **Python randomises string hashing per
    process**, so `random.Random((seed, station_id, hour).__hash__())` draws a different
    number after every restart while looking entirely deterministic.

    That shipped here and was caught by an agent asking the mock for the same hour twice and
    getting 67.9 mm, then 54.4 mm. Nothing raised. The demo simply showed different weather
    each time it was booted, and any test that pinned a value would have been quietly flaky.

    So the seed comes from a digest, which is stable across processes, restarts and Python
    versions. Used for its stability and distribution, not for any security property.
    """
    joined = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(f"seed:{joined}".encode()).digest()
    return int.from_bytes(digest[:_DIGEST_BYTES], "big")
