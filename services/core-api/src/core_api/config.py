"""Settings for core-api.

Shared infrastructure values live in the SARANA_ namespace and are inherited. Anything
specific to this service is read from its own SARANA_CORE_ block, declared field by field
so the variable name in the environment is visible here rather than assembled by magic.

Missing or malformed values stop the process at boot naming the variable - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core_api.gateway.proxy import Downstream
from sarana_shared.config import SharedSettings, load_settings_or_exit


class Settings(SharedSettings):
    """Configuration for core-api."""

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
        validation_alias="SARANA_CORE_HOST",
    )
    port: int = Field(default=8001, ge=1, le=65535, validation_alias="SARANA_CORE_PORT")
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias="SARANA_CORE_CORS_ORIGINS"
    )

    # The services core-api routes to. Declared field by field rather than parsed from one
    # blob, so a missing downstream is a named configuration error at boot instead of a
    # KeyError the first time someone opens the incident map.
    incident_svc_url: str = Field(
        default="http://incident-svc:8002", validation_alias="SARANA_CORE_INCIDENT_SVC_URL"
    )
    alerting_svc_url: str = Field(
        default="http://alerting-svc:8003", validation_alias="SARANA_CORE_ALERTING_SVC_URL"
    )
    ledger_svc_url: str = Field(
        default="http://ledger-svc:8004", validation_alias="SARANA_CORE_LEDGER_SVC_URL"
    )
    agent_svc_url: str = Field(
        default="http://agent-svc:8005", validation_alias="SARANA_CORE_AGENT_SVC_URL"
    )

    def downstreams(self) -> dict[str, Downstream]:
        """The routing table, keyed by the name used as the internal token audience."""
        return {
            "incident-svc": Downstream(name="incident-svc", base_url=self.incident_svc_url),
            "alerting-svc": Downstream(name="alerting-svc", base_url=self.alerting_svc_url),
            "ledger-svc": Downstream(name="ledger-svc", base_url=self.ledger_svc_url),
            "agent-svc": Downstream(name="agent-svc", base_url=self.agent_svc_url),
        }


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
