"""Settings for alerting-svc.

Shared infrastructure values live in the SARANA_ namespace and are inherited. Anything
specific to this service is read from its own SARANA_ALERTING_ block, declared field by field
so the variable name in the environment is visible here rather than assembled by magic.

Missing or malformed values stop the process at boot naming the variable - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from sarana_shared.config import SharedSettings, load_settings_or_exit


class Settings(SharedSettings):
    """Configuration for alerting-svc."""

    model_config = SettingsConfigDict(
        env_prefix="SARANA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    host: str = Field(
        default="0.0.0.0",  # noqa: S104 - bound inside a container network, not the host
        validation_alias="SARANA_ALERTING_HOST",
    )
    port: int = Field(default=8003, ge=1, le=65535, validation_alias="SARANA_ALERTING_PORT")
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias="SARANA_ALERTING_CORS_ORIGINS"
    )

    # The CAP <sender>. Must identify the issuing authority, because a consumer decides
    # whether to trust an alert by who sent it.
    # Where the household directory lives, and the credential that reads it. The secret is
    # provisioned by `tools/seed/service_clients.py`; without it the directory falls back
    # to one that resolves nothing and says so on every attempt, so a deployment that
    # forgot it does not silently stop telling households about their payments.
    core_api_url: str = Field(
        default="http://localhost:8001", validation_alias="SARANA_CORE_API_URL"
    )
    client_id: str = Field(default="alerting-svc", validation_alias="SARANA_ALERTING_CLIENT_ID")
    client_secret: str | None = Field(
        default=None, validation_alias="SARANA_ALERTING_CLIENT_SECRET"
    )
    # Zero disables the payment-notice consumer. For tooling and tests that have no
    # business subscribing to a stream and sending messages.
    payment_notices_enabled: bool = Field(
        default=True, validation_alias="SARANA_ALERTING_PAYMENT_NOTICES_ENABLED"
    )

    cap_sender: str = Field(default="dmc@sarana.lk", validation_alias="SARANA_ALERTING_CAP_SENDER")

    # A misconfigured area selection that targets all 14,022 divisions must be stopped
    # before twenty million messages. Above this, dispatch requires an explicit override
    # and a written reason.
    alert_target_cap: int = Field(
        default=250_000, ge=1, validation_alias="SARANA_ALERTING_TARGET_CAP"
    )


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
