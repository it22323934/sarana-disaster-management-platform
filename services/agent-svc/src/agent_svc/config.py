"""Settings for agent-svc.

Shared infrastructure values live in the SARANA_ namespace and are inherited. Anything
specific to this service is read from its own SARANA_AGENT_ block, declared field by field
so the variable name in the environment is visible here rather than assembled by magic.

Missing or malformed values stop the process at boot naming the variable - never a
KeyError at request time, three hours into a cyclone.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from sarana_shared.config import SharedSettings, load_settings_or_exit


class Settings(SharedSettings):
    """Configuration for agent-svc."""

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
        validation_alias="SARANA_AGENT_HOST",
    )
    port: int = Field(default=8005, ge=1, le=65535, validation_alias="SARANA_AGENT_PORT")
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias="SARANA_AGENT_CORS_ORIGINS"
    )

    # The model provider. Absent, every agent runs its deterministic path and says so -
    # which is the behaviour a blackout produces, so a laptop with no key exercises the
    # same code the platform falls back to during an outage.
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    # Per-tier model identifiers. Overridable because a model identifier is a fact about
    # the provider's catalogue on a given day, not a fact about this platform.
    model_volume: str | None = Field(default=None, validation_alias="SARANA_AGENT_MODEL_VOLUME")
    model_standard: str | None = Field(default=None, validation_alias="SARANA_AGENT_MODEL_STANDARD")
    model_escalated: str | None = Field(
        default=None, validation_alias="SARANA_AGENT_MODEL_ESCALATED"
    )

    # The daily spend cap. Reaching it drops every tier to VOLUME and then to the
    # deterministic paths, with an alert. Cost must not be able to page somebody at 3 a.m.
    # during a cyclone.
    daily_spend_cap_usd: float = Field(
        default=50.0, ge=0.0, validation_alias="SARANA_AGENT_DAILY_SPEND_CAP_USD"
    )

    # Durable checkpointing. False uses an in-process saver, which loses every paused run
    # on restart - fine for a test, catastrophic in a deployment, and the boot log says so.
    durable_checkpoints: bool = Field(
        default=True, validation_alias="SARANA_AGENT_DURABLE_CHECKPOINTS"
    )

    # Where the forecast agent reads its inputs, and the credential that opens core-api.
    # The secret is provisioned by `tools/seed/service_clients.py`; without it the agent
    # refuses to run rather than scoring every division against a default hazard zone, so
    # a deployment that forgot it fails visibly instead of forecasting confidently wrong.
    core_api_url: str = Field(
        default="http://localhost:8001", validation_alias="SARANA_CORE_API_URL"
    )
    gov_mock_url: str = Field(
        default="http://localhost:8006", validation_alias="SARANA_GOV_MOCK_URL"
    )

    # Where the warning agent reads the template catalogue and sends alerts. Without it the
    # agent keeps its refusing stand-ins rather than completing a run that warned nobody.
    alerting_url: str = Field(
        default="http://localhost:8003", validation_alias="SARANA_ALERTING_SVC_URL"
    )

    # Who the CAP documents this service produces say sent them. Matches alerting-svc's own
    # default: two services disagreeing about the sender of one alert is a consumer
    # deduplicating two warnings into none.
    cap_sender: str = Field(default="dmc@sarana.lk", validation_alias="SARANA_ALERTING_CAP_SENDER")
    client_id: str = Field(default="agent-svc", validation_alias="SARANA_AGENT_CLIENT_ID")
    client_secret: str | None = Field(default=None, validation_alias="SARANA_AGENT_CLIENT_SECRET")

    langsmith_api_key: str | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="sarana", validation_alias="LANGSMITH_PROJECT")
    tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
