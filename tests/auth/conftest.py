"""Fixtures for the authentication and authorisation suite.

Reuses the migrated-database fixtures from the schema suite: several of these rules are
enforced by database triggers and grants, and testing them anywhere else would prove
nothing about whether they actually hold.
"""

from __future__ import annotations

import pytest

from sarana_shared.auth.tokens import TokenService, TokenSettings
from sarana_shared.crypto.keyed import FieldCipher, KeyedHasher
from tests.schema.conftest import (  # noqa: F401 - re-exported as fixtures
    REPO_ROOT,
    db,
    migrated_url,
    schema_engine,
)


@pytest.fixture(scope="session")
def token_service() -> TokenService:
    """A token service using the local development keypair."""
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return TokenService(
        TokenSettings(
            public_key_path=keys / "jwt-public.pem",
            private_key_path=keys / "jwt-private.pem",
            issuer="https://sarana.lk",
            audience="sarana-api",
        )
    )


@pytest.fixture(scope="session")
def keyed_hasher() -> KeyedHasher:
    """Deterministic HMAC for refresh tokens, phone numbers and lockout keys."""
    return KeyedHasher(key=bytes.fromhex("11" * 32))


@pytest.fixture(scope="session")
def field_cipher() -> FieldCipher:
    """Field-level encryption for personal data."""
    return FieldCipher(key=bytes.fromhex("22" * 32))
