"""pydantic-settings config, prefixed SARANA_GOV_MOCK_ per
docs/build-prompts/02-conventions.md.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SARANA_GOV_MOCK_", extra="ignore")

    port: int = 8006
    database_url: str
    event_bus: str = "redis_streams"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    # Failure-injection defaults per docs/build-prompts/11-gov-mock-services.md:
    # "on by default in dev" — a system that only works at 0% chaos is not built.
    chaos_timeout_pct: int = 5
    chaos_error_pct: int = 5
    chaos_malformed_pct: int = 5


def get_settings() -> Settings:
    return Settings()
