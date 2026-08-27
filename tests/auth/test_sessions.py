"""Refresh-token rotation, reuse detection, and the failed-login backoff."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from core_api.domain.auth.lockout import (
    FREE_ATTEMPTS,
    MAX_DELAY,
    delay_for,
    next_lock_until,
)
from core_api.domain.auth.sessions import (
    RefreshOutcome,
    RefreshRejected,
    StoredRefreshToken,
    classify,
    mint,
    revokes_family,
)
from sarana_shared.crypto.keyed import KeyedHasher
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

pytestmark = pytest.mark.asyncio(loop_scope="session")


def stored(token, **overrides):  # type: ignore[no-untyped-def]  # test helper
    defaults = {
        "token_id": token.token_id,
        "user_id": uuid7(),
        "device_id": uuid7(),
        "family_id": token.family_id,
        "expires_at": utc_now() + timedelta(days=30),
        "used_at": None,
        "revoked_at": None,
    }
    return StoredRefreshToken(**{**defaults, **overrides})


async def test_only_the_hash_is_ever_stored(keyed_hasher: KeyedHasher) -> None:
    """A database dump must contain no usable session credentials."""
    token = mint(keyed_hasher)

    assert token.token_hash != token.secret
    assert keyed_hasher.hash(token.secret) == token.token_hash


async def test_a_fresh_token_rotates(keyed_hasher: KeyedHasher) -> None:
    token = mint(keyed_hasher)

    assert classify(stored(token)) is RefreshOutcome.ROTATED


async def test_reuse_revokes_the_whole_device_family(keyed_hasher: KeyedHasher) -> None:
    """Case 7: a token presented twice ends every session descended from that login.

    A retry after a lost response and a stolen copy are indistinguishable from here, and
    only one of them is safe to ignore. The cost of being wrong this way is one extra
    login.
    """
    token = mint(keyed_hasher)

    outcome = classify(stored(token, used_at=utc_now()))

    assert outcome is RefreshOutcome.REUSED
    assert revokes_family(outcome)


async def test_reuse_is_detected_even_when_the_token_also_expired(
    keyed_hasher: KeyedHasher,
) -> None:
    """Treating a replayed expired token as a plain expiry would discard the evidence."""
    token = mint(keyed_hasher)

    outcome = classify(stored(token, used_at=utc_now(), expires_at=utc_now() - timedelta(days=1)))

    assert outcome is RefreshOutcome.REUSED


async def test_every_rejection_says_the_same_thing() -> None:
    """Distinguishing 'unknown' from 'revoked' hands an attacker a probing oracle."""
    messages = {str(RefreshRejected(outcome)) for outcome in RefreshOutcome}

    assert len(messages) == 1


async def test_an_unknown_token_is_rejected() -> None:
    assert classify(None) is RefreshOutcome.UNKNOWN


async def test_the_first_few_failures_are_free() -> None:
    """Fat fingers on a phone keyboard in the rain are not an attack."""
    assert delay_for(FREE_ATTEMPTS) == timedelta(0)
    assert delay_for(FREE_ATTEMPTS + 1) > timedelta(0)


async def test_backoff_grows_but_never_locks_permanently() -> None:
    """A GN officer locked out during a cyclone is a safety problem, not a security win."""
    assert delay_for(8) > delay_for(6)
    assert delay_for(50) == MAX_DELAY
    assert delay_for(10_000) == MAX_DELAY
    assert timedelta(minutes=15) == MAX_DELAY


async def test_no_lock_is_recorded_while_attempts_are_free() -> None:
    assert next_lock_until(FREE_ATTEMPTS) is None
    assert next_lock_until(FREE_ATTEMPTS + 1) is not None


async def test_a_login_attempt_cannot_be_rewritten(db: AsyncConnection) -> None:
    """The lockout trail is evidence. Rewriting it is what an intruder would want."""
    await db.execute(
        text(
            "INSERT INTO admin.login_attempt "
            "(id, account_hash, source_hash, succeeded, failure_reason, correlation_id) "
            "VALUES (:id, :account, :source, false, 'BAD_PASSWORD', 'test')"
        ),
        {"id": uuid7(), "account": "a" * 64, "source": "b" * 64},
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("UPDATE admin.login_attempt SET succeeded = true"))


async def test_a_security_event_cannot_be_deleted(db: AsyncConnection) -> None:
    await db.execute(
        text(
            "INSERT INTO admin.security_event (id, kind, detail, correlation_id) "
            "VALUES (:id, 'REFRESH_REUSE', '{\"family\": \"redacted\"}'::jsonb, 'test')"
        ),
        {"id": uuid7()},
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text("DELETE FROM admin.security_event"))
