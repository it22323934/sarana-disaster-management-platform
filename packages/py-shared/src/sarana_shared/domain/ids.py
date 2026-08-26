"""UUIDv7 primary keys, correlation ids, and short human-readable reference codes.

Per docs/build-prompts/02-conventions.md: every entity PK is a UUIDv7 (time-ordered,
index-friendly); public-facing references use a short code, never the raw UUID.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from uuid import UUID

from uuid6 import uuid7 as _uuid7

_BASE32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford, no ambiguous chars


def uuid7() -> UUID:
    """A time-ordered UUIDv7. Use this, never uuid4, for every entity primary key."""
    return _uuid7()


def new_correlation_id() -> UUID:
    """A correlation id that must survive an entire event chain — mint once, never regenerate."""
    return uuid7()


def _random_base32(length: int) -> str:
    return "".join(secrets.choice(_BASE32_ALPHABET) for _ in range(length))


def short_code(prefix: str, *, when: date | datetime | None = None, length: int = 6) -> str:
    """A public-facing reference code, e.g. INC-260901-K3F9QZ or CLM-260901-7HTN2A.

    Never the entity's UUID — this is what a citizen sees on a confirmation SMS or a
    ledger row, and what they'd read back over a phone call.
    """
    moment = when or datetime.now(UTC)
    yymmdd = moment.strftime("%y%m%d")
    return f"{prefix}-{yymmdd}-{_random_base32(length)}"


def is_valid_short_code(code: str, *, prefix: str) -> bool:
    """Cheap format validation for a short code — not a database lookup."""
    expected_prefix = f"{prefix}-"
    if not code.startswith(expected_prefix):
        return False
    rest = code[len(expected_prefix) :]
    parts = rest.split("-")
    if len(parts) != 2:
        return False
    yymmdd, suffix = parts
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return False
    return all(c in _BASE32_ALPHABET for c in suffix)
