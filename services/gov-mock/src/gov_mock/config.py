"""Settings for gov-mock.

Shared infrastructure values live in the SARANA_ namespace and are inherited. Anything
specific to this service is read from its own SARANA_GOV_MOCK_ block, declared field by field
so the variable name in the environment is visible here rather than assembled by magic.

Missing or malformed values stop the process at boot naming the variable - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from sarana_shared.config import SharedSettings, load_settings_or_exit


class Settings(SharedSettings):
    """Configuration for gov-mock."""

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
        validation_alias="SARANA_GOV_MOCK_HOST",
    )
    port: int = Field(default=8006, ge=1, le=65535, validation_alias="SARANA_GOV_MOCK_PORT")
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias="SARANA_GOV_MOCK_CORS_ORIGINS"
    )

    # The seed for every generator in this service. A demo replayed from a fresh container
    # produces the same rainfall, the same households and the same injected failures in
    # the same order - which is what makes a scenario reproducible rather than a story.
    seed: int = Field(default=20251128, validation_alias="SARANA_GOV_MOCK_SEED")

    # Failure injection. Defaults are build file 11's: 5% each, on in dev, because a
    # platform that only works at 0% is not built. Tests set them to zero and the chaos
    # suite sets them to 100.
    timeout_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, validation_alias="SARANA_GOV_MOCK_TIMEOUT_PCT"
    )
    error_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, validation_alias="SARANA_GOV_MOCK_ERROR_PCT"
    )
    malformed_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, validation_alias="SARANA_GOV_MOCK_MALFORMED_PCT"
    )
    stale_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, validation_alias="SARANA_GOV_MOCK_STALE_PCT"
    )
    latency_ms: int = Field(
        default=250, ge=0, le=60_000, validation_alias="SARANA_GOV_MOCK_LATENCY_MS"
    )

    # Where the inbound simulator posts a citizen's SMS or USSD turn, and the credential it
    # uses. The token stays server-side: putting a long-lived INCIDENT_WRITE credential
    # into a page anybody at a demo can open would hand out the ability to file reports as
    # the telco gateway.
    incident_svc_url: str = Field(
        default="http://localhost:8002", validation_alias="SARANA_INCIDENT_SVC_URL"
    )
    incident_service_token: str | None = Field(
        default=None, validation_alias="SARANA_INCIDENT_SERVICE_TOKEN"
    )


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
