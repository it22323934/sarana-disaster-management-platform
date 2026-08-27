"""Identifier generation: UUIDv7 primary keys, public short codes, correlation IDs.

Conventions:
  - Every entity PK is a UUIDv7 (time-ordered, index-friendly).
  - Every event carries an `event_id` and a `correlation_id` that survives the whole
    chain from raw citizen report to disbursement. Never break the chain.
  - Public-facing references use a short human-readable code, never the UUID.
"""

from __future__ import annotations

import secrets
import threading
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

# Crockford base32: no I, L, O or U, so a code cannot be misread over a phone line
# or mistyped from a printed relief docket.
_CROCKFORD_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_SHORT_CODE_LENGTH: Final = 6

# UUIDv7 layout (RFC 9562 section 5.7):
#   48 bits unix_ts_ms | 4 bits version | 12 bits rand_a | 2 bits variant | 62 bits rand_b
# rand_a is used as a monotonic counter so that two IDs minted in the same millisecond
# still sort in creation order - which is what makes these usable as index keys.
_UUID7_LOCK: Final = threading.Lock()
_uuid7_last_ms: int = -1
_uuid7_counter: int = 0

_MAX_COUNTER: Final = 0xFFF

_correlation_id: ContextVar[str | None] = ContextVar("sarana_correlation_id", default=None)


def uuid7() -> UUID:
    """Return a time-ordered UUID version 7.

    Monotonic within a process: IDs minted in the same millisecond increment a 12-bit
    counter rather than colliding on sort order.
    """
    global _uuid7_last_ms, _uuid7_counter

    with _UUID7_LOCK:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        if now_ms == _uuid7_last_ms:
            _uuid7_counter += 1
            if _uuid7_counter > _MAX_COUNTER:
                # Counter exhausted inside one millisecond: borrow from the next one
                # rather than emit an out-of-order ID.
                _uuid7_last_ms += 1
                now_ms = _uuid7_last_ms
                _uuid7_counter = 0
        else:
            _uuid7_last_ms = now_ms
            # Leave headroom to increment without overflowing within the millisecond.
            _uuid7_counter = secrets.randbits(10)

        timestamp_ms = now_ms
        counter = _uuid7_counter

    rand_b = secrets.randbits(62)

    value = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= (counter & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand_b

    return UUID(int=value)


def uuid7_timestamp(value: UUID) -> datetime:
    """Extract the creation timestamp embedded in a UUIDv7.

    Raises:
        ValueError: if value is not a version 7 UUID.
    """
    if value.version != 7:
        raise ValueError(f"expected a UUIDv7, got version {value.version}")
    timestamp_ms = value.int >> 80
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _random_base32(length: int) -> str:
    """Return length cryptographically random Crockford base32 characters."""
    return "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(length))


def short_code(prefix: str, *, at: datetime | None = None) -> str:
    """Build a public, human-readable reference such as INC-260826-K3M9PQ.

    Args:
        prefix: Entity marker, e.g. INC for incident or CLM for claim.
        at: Timestamp the code is dated from. Defaults to now. Must be timezone-aware.

    The date segment is YYMMDD in UTC, matching how the record is stored. Rendering the
    code alongside a Colombo-local date is a presentation concern, not an identity one.
    """
    if not prefix.isalpha() or not prefix.isupper():
        raise ValueError(f"short-code prefix must be uppercase letters, got {prefix!r}")

    moment = at or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("short_code() requires a timezone-aware datetime")

    datestamp = moment.astimezone(UTC).strftime("%y%m%d")
    return f"{prefix}-{datestamp}-{_random_base32(_SHORT_CODE_LENGTH)}"


def new_correlation_id() -> str:
    """Mint a fresh correlation ID for a chain that starts here."""
    return str(uuid7())


def get_correlation_id() -> str | None:
    """Return the correlation ID bound to the current context, if any."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> None:
    """Bind a correlation ID to the current context.

    Called by the inbound HTTP middleware and by the event-bus consumer loop, so every
    log line and every event published downstream carries the same chain ID.

    Raises:
        ValueError: if the value is not a UUID. The event envelope types this field as a
            UUID, so a non-UUID bound here would not fail until something tried to
            publish - turning a caller's mistake into a lost event somewhere else
            entirely. `parse_correlation_id` is the forgiving version, for untrusted
            input like an inbound header.
    """
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(
            f"correlation id must be a UUID, got {value!r}. Use parse_correlation_id() "
            "for values that come from outside the platform."
        ) from exc
    _correlation_id.set(value)


def ensure_correlation_id() -> str:
    """Return the current correlation ID, minting and binding one if absent."""
    current = _correlation_id.get()
    if current is None:
        current = new_correlation_id()
        _correlation_id.set(current)
    return current


def reset_correlation_id() -> None:
    """Clear the correlation ID. Used by test fixtures between cases."""
    _correlation_id.set(None)


def ensure_correlation_uuid() -> UUID:
    """The current correlation ID as a UUID, minting and binding one if absent.

    The envelope types this field as a UUID rather than free text on purpose. A
    correlation ID travels through logs, event payloads and audit entries, and anything
    an inbound caller can put in a header ends up in all three - so it has to be a shape
    we control rather than a string we forward.
    """
    return UUID(ensure_correlation_id())


def parse_correlation_id(value: str | None) -> str | None:
    """Accept an inbound correlation ID only if it is a UUID.

    Returning None means "mint a fresh one". Honouring an arbitrary header value would
    let a caller choose what appears in the audit trail beside their own actions, and
    would put unvalidated text into every log line the request produces.
    """
    if not value:
        return None
    candidate = value.strip()
    try:
        return str(UUID(candidate))
    except ValueError:
        return None
