"""Base settings every service inherits.

Env vars follow `SARANA_{SERVICE}_{KEY}`; the shared settings below read the unprefixed
`SARANA_` namespace, and each service adds its own prefixed block on top.

No service starts if a required variable is missing. `load_settings` turns a pydantic
ValidationError into a boot-time message naming the variable, and exits - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from sarana_shared.auth.tokens import TokenSettings
from sarana_shared.crypto.keyed import FieldCipher, KeyedHasher
from sarana_shared.db.session import DatabaseSettings
from sarana_shared.events.bus import BusKind

ENV_FILE: Final = ".env"


class Environment(StrEnum):
    """Where this process is running. Drives log format and safety guards."""

    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

    @property
    def is_production_like(self) -> bool:
        """Whether guards that must never be relaxed in a real deployment apply."""
        return self in (Environment.STAGING, Environment.PROD)


class SharedSettings(BaseSettings):
    """Configuration common to every SARANA service."""

    model_config = SettingsConfigDict(
        env_prefix="SARANA_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Field(default=Environment.LOCAL)
    instance: str = Field(default="local")

    database_url: str = Field(description="Async SQLAlchemy DSN (postgresql+asyncpg://...)")
    database_echo: bool = Field(default=False)
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_statement_timeout_ms: int = Field(default=15_000, ge=100)

    redis_url: str = Field(default="redis://localhost:6379/0")
    event_stream_prefix: str = Field(default="sarana")

    # Which EventBus implementation to build. `redis` locally and in CI, `eventbridge` on
    # AWS, `memory` for unit tests. ADR-003 keeps the port open for an `msk` in Phase 2.
    event_bus: BusKind = Field(default=BusKind.REDIS)
    # EventBridge only. Ignored by the other implementations.
    event_bus_name: str = Field(default="sarana")
    aws_region: str = Field(default="ap-south-1")

    jwt_public_key_path: Path
    jwt_private_key_path: Path | None = Field(default=None)
    jwt_issuer: str = Field(default="https://sarana.lk")
    jwt_audience: str = Field(default="sarana-api")
    access_token_ttl_seconds: int = Field(default=900, ge=60)
    refresh_token_ttl_seconds: int = Field(default=2_592_000, ge=3_600)

    # Keyed hashing and field encryption for personal data. Hex-encoded, 32 bytes, from
    # Secrets Manager on AWS. They are separate keys on purpose: the HMAC key is used for
    # deterministic lookup and the cipher key for recoverable ciphertext, and a single key
    # doing both would let anyone able to compute a lookup hash also decrypt the field.
    pii_hmac_key: str = Field(
        description="Hex-encoded HMAC-SHA256 key for MSISDN and account lookup hashes"
    )
    pii_cipher_key: str = Field(
        description="Hex-encoded AES-256 key for field-level encryption of personal data"
    )

    otlp_endpoint: str | None = Field(default=None)
    tracing_enabled: bool = Field(default=True)

    log_level: str = Field(default="INFO")

    @property
    def json_logs(self) -> bool:
        """JSON everywhere except a developer's own machine."""
        return self.env is not Environment.LOCAL

    def database(self, *, application_name: str) -> DatabaseSettings:
        """Build the engine settings for one service."""
        return DatabaseSettings(
            url=self.database_url,
            echo=self.database_echo,
            pool_size=self.database_pool_size,
            statement_timeout_ms=self.database_statement_timeout_ms,
            application_name=application_name,
        )

    def keyed_hasher(self) -> KeyedHasher:
        """Build the deterministic hasher used for lookup keys."""
        return KeyedHasher.from_hex(self.pii_hmac_key)

    def field_cipher(self) -> FieldCipher:
        """Build the cipher used for recoverable personal data."""
        return FieldCipher.from_hex(self.pii_cipher_key)

    def tokens(self, *, can_issue: bool = False) -> TokenSettings:
        """Build token settings.

        `can_issue=True` only for core-api. Every other service verifies with the public
        key alone and cannot mint a token even if it is compromised.
        """
        return TokenSettings(
            public_key_path=self.jwt_public_key_path,
            private_key_path=self.jwt_private_key_path if can_issue else None,
            issuer=self.jwt_issuer,
            audience=self.jwt_audience,
            access_ttl=timedelta(seconds=self.access_token_ttl_seconds),
            refresh_ttl=timedelta(seconds=self.refresh_token_ttl_seconds),
        )


class MissingConfiguration(RuntimeError):
    """One or more required environment variables are absent or malformed."""


def _env_var_name(settings_class: type[BaseSettings], field_path: tuple[object, ...]) -> str:
    """Render a pydantic field location as the environment variable an operator sets."""
    prefix = settings_class.model_config.get("env_prefix", "")
    field_name = ".".join(str(part) for part in field_path)
    return f"{prefix}{field_name}".upper()


def load_settings[S: BaseSettings](settings_class: type[S]) -> S:
    """Instantiate a settings class, failing loudly and readably if anything is missing.

    Raises:
        MissingConfiguration: naming every variable that is absent or invalid.
    """
    try:
        # Values come from the environment, not from arguments.
        return settings_class()
    except ValidationError as exc:
        lines: list[str] = []
        for error in exc.errors():
            variable = _env_var_name(settings_class, error.get("loc", ()))
            lines.append(f"  {variable}: {error.get('msg', 'invalid')}")
        raise MissingConfiguration(
            f"{settings_class.__name__} could not be loaded. "
            f"Fix these environment variables and restart:\n" + "\n".join(sorted(lines))
        ) from exc


def load_settings_or_exit[S: BaseSettings](settings_class: type[S]) -> S:
    """`load_settings`, but writes the problem to stderr and exits 78 on failure.

    Exit code 78 is EX_CONFIG from sysexits.h, so a container orchestrator can tell a
    misconfiguration apart from a crash and stop restarting the task.
    """
    try:
        return load_settings(settings_class)
    except MissingConfiguration as exc:
        sys.stderr.write(f"\nSARANA configuration error\n\n{exc}\n\n")
        raise SystemExit(78) from exc
