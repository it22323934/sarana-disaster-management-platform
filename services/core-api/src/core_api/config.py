"""pydantic-settings config, prefixed SARANA_CORE_API_ per
docs/build-prompts/02-conventions.md ("Env vars: SARANA_{SERVICE}_{KEY}").

No service starts if a required env var is missing — fail loudly at boot with the
variable name, never with a KeyError at request time (docs/build-prompts/03).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SARANA_CORE_API_", extra="ignore")

    port: int = 8001
    database_url: str
    event_bus: str = "redis_streams"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"


def get_settings() -> Settings:
    # Constructed on first call, not at import time, so a missing env var surfaces as a
    # clear startup error inside main.py's lifespan rather than an import-time crash
    # that's harder to attribute to "which service, which variable."
    return Settings()
