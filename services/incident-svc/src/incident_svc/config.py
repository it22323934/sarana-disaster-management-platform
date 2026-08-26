"""pydantic-settings config, prefixed SARANA_INCIDENT_SVC_ per
docs/build-prompts/02-conventions.md.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SARANA_INCIDENT_SVC_", extra="ignore")

    port: int = 8002
    database_url: str
    event_bus: str = "redis_streams"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"


def get_settings() -> Settings:
    return Settings()
