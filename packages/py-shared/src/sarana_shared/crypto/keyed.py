"""Keyed hashing and field-level encryption.

Two distinct jobs that are easy to confuse:

**KeyedHasher** produces a deterministic HMAC used as a lookup key. An inbound SMS can be
resolved to a household by hashing the sender's number and matching the stored HMAC, so
the platform never decrypts a phone number just to route a message. Deterministic is the
point - and also the limitation, because equal inputs give equal outputs and the set of
possible phone numbers is small enough to enumerate. That is why the key lives in Secrets
Manager and never in the database beside the hashes it protects.

**FieldCipher** encrypts a value that must be recoverable - a name to print on a payment
docket, a number to actually send an SMS to. AES-GCM, with the record's own identifier as
associated data so a ciphertext moved to a different row fails to decrypt rather than
silently identifying the wrong household.

ADR-011: this data leaves Sri Lanka to run in ap-south-1. PDPA No. 9 of 2022 has no
cross-border rule in force today, but there will be one, and a government partner asks on
day one. Field-level encryption is the answer being ready rather than promised.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# AES-GCM nonces must never repeat under one key. 96 bits is the standard size and is
# generated fresh per encryption from the OS CSPRNG.
NONCE_BYTES: Final = 12

MIN_KEY_BYTES: Final = 32


class WeakKey(ValueError):
    """A key is too short to be used."""


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two secrets without leaking their difference through timing."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class KeyedHasher:
    """Deterministic HMAC-SHA256, for looking up a value without storing it."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) < MIN_KEY_BYTES:
            raise WeakKey(
                f"a keyed-hash key must be at least {MIN_KEY_BYTES} bytes; got {len(self.key)}"
            )

    @classmethod
    def from_hex(cls, value: str) -> KeyedHasher:
        """Build from the hex-encoded key held in Secrets Manager."""
        return cls(key=bytes.fromhex(value))

    def hash(self, value: str) -> str:
        """Hex HMAC of a value. Stable across processes and deployments."""
        return hmac.new(self.key, value.encode("utf-8"), sha256).hexdigest()

    def matches(self, value: str, stored_hash: str) -> bool:
        """Whether a value hashes to a stored HMAC, compared in constant time."""
        return constant_time_equals(self.hash(value), stored_hash)


@dataclass(frozen=True, slots=True)
class FieldCipher:
    """AES-GCM field encryption, bound to the row it belongs to."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) not in (16, 24, 32):
            raise WeakKey(f"an AES key must be 16, 24 or 32 bytes; got {len(self.key)}")

    @classmethod
    def from_hex(cls, value: str) -> FieldCipher:
        """Build from the hex-encoded key held in Secrets Manager."""
        return cls(key=bytes.fromhex(value))

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        """Encrypt a value, binding it to `context`.

        `context` is the row's identifier. It is authenticated but not encrypted, so a
        ciphertext copied into another row fails to decrypt instead of quietly producing
        the wrong household's name on a payment docket.
        """
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self.key).encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return nonce + sealed

    def decrypt(self, ciphertext: bytes, *, context: str) -> str:
        """Decrypt a value that was bound to `context`.

        Raises:
            cryptography.exceptions.InvalidTag: if the ciphertext was altered, or if it
                belongs to a different row.
        """
        nonce, sealed = ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:]
        opened = AESGCM(self.key).decrypt(nonce, sealed, context.encode("utf-8"))
        return opened.decode("utf-8")
