"""Settings for incident-svc.

Shared infrastructure values live in the SARANA_ namespace and are inherited. Anything
specific to this service is read from its own SARANA_INCIDENT_ block, declared field by field
so the variable name in the environment is visible here rather than assembled by magic.

Missing or malformed values stop the process at boot naming the variable - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from sarana_shared.config import SharedSettings, load_settings_or_exit


class Settings(SharedSettings):
    """Configuration for incident-svc."""

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
        validation_alias="SARANA_INCIDENT_HOST",
    )
    port: int = Field(default=8002, ge=1, le=65535, validation_alias="SARANA_INCIDENT_PORT")
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias="SARANA_INCIDENT_CORS_ORIGINS"
    )

    # Resolving a coordinate to a GN division is the one core-api call on the intake path.
    # Named here rather than assembled, so a missing value is a configuration error at boot
    # instead of a failure the first time a citizen reports something.
    core_api_url: str = Field(
        default="http://core-api:8001", validation_alias="SARANA_INCIDENT_CORE_API_URL"
    )

    # This service calls core-api as a machine, not on behalf of the reporter. A citizen
    # holds `incident:write` and deliberately not `admin:read`, so forwarding their token
    # would fail for exactly the people who report the most.
    #
    # In a deployment this comes from the secret store. Locally `make service-token`
    # mints one. Absent, reports are still accepted and simply arrive unplaced, which is
    # the documented degraded behaviour rather than a new failure mode.
    # The client-credentials grant this service authenticates with. Provisioned by
    # `tools/seed/service_clients.py`; holds `admin:read` and nothing else.
    client_id: str = Field(default="incident-svc", validation_alias="SARANA_INCIDENT_CLIENT_ID")
    client_secret: str | None = Field(
        default=None, validation_alias="SARANA_INCIDENT_CLIENT_SECRET"
    )


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
