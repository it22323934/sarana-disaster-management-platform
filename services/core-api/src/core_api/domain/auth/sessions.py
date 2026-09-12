"""Refresh-token rotation, and what to do when a token comes back twice.

A refresh token is single-use. Exchanging it mints a replacement in the same family and
marks the old one used. If a used token is presented again, one of two things happened:
the legitimate client retried after a response it never received, or somebody else has a
copy.

From here those are indistinguishable, and only one of them is safe to ignore. So both
are treated as compromise: the whole device family is revoked, a security event is
raised, and the user signs in again. The cost of being wrong in that direction is one
extra login. The cost of being wrong in the other direction is a live session in someone
else's hands.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from sarana_shared.crypto.keyed import KeyedHasher
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

# Opaque and long. A refresh token is not a JWT: there is nothing a client needs to read
# inside it, and an opaque token can be revoked by deleting a row.
TOKEN_BYTES: Final = 32

DEFAULT_TTL: Final = timedelta(days=30)


class RefreshOutcome(StrEnum):
    """What happened when a refresh token was presented."""

    ROTATED = "ROTATED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REUSED = "REUSED"


class RefreshRejected(Exception):
    """The refresh token was not exchanged, and why."""

    def __init__(self, outcome: RefreshOutcome) -> None:
        super().__init__(_REJECTION_MESSAGES[outcome])
        self.outcome = outcome


# What the client is told. Deliberately identical for every failure: distinguishing
# "unknown token" from "revoked token" tells a holder of stolen tokens which ones were
# real, which is a probing oracle.
_REJECTION_MESSAGES: Final[dict[RefreshOutcome, str]] = dict.fromkeys(
    RefreshOutcome, "Your session has ended. Sign in again."
)


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """A new refresh token: the secret for the client, the hash for the database."""

    token_id: UUID
    family_id: UUID
    secret: str
    token_hash: str
    expires_at: datetime


def mint(
    hasher: KeyedHasher,
    *,
    family_id: UUID | None = None,
    ttl: timedelta = DEFAULT_TTL,
    now: datetime | None = None,
) -> IssuedRefreshToken:
    """Create a refresh token. A new family when `family_id` is omitted.

    Only the hash is stored. A database dump therefore contains no usable session
    credentials, which is the whole reason for hashing something the server generated
    itself.
    """
    secret = secrets.token_urlsafe(TOKEN_BYTES)
    return IssuedRefreshToken(
        token_id=uuid7(),
        family_id=family_id or uuid7(),
        secret=secret,
        token_hash=hasher.hash(secret),
        expires_at=(now or utc_now()) + ttl,
    )


@dataclass(frozen=True, slots=True)
class StoredRefreshToken:
    """The row a presented token resolved to."""

    token_id: UUID
    user_id: UUID
    device_id: UUID
    family_id: UUID
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


def classify(stored: StoredRefreshToken | None, *, now: datetime | None = None) -> RefreshOutcome:
    """Decide what a presented refresh token means.

    Ordered so that reuse is detected before expiry: a replayed token that has also
    expired is still a reuse signal, and treating it as a plain expiry would discard the
    evidence.
    """
    if stored is None:
        return RefreshOutcome.UNKNOWN
    if stored.used_at is not None:
        return RefreshOutcome.REUSED
    if stored.revoked_at is not None:
        return RefreshOutcome.REVOKED
    if (now or utc_now()) >= stored.expires_at:
        return RefreshOutcome.EXPIRED
    return RefreshOutcome.ROTATED


def revokes_family(outcome: RefreshOutcome) -> bool:
    """Whether this outcome ends every session descended from the same login."""
    return outcome is RefreshOutcome.REUSED
