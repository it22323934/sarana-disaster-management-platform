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


def get_settings() -> Settings:
    """Load settings, exiting 78 (EX_CONFIG) if the environment is incomplete."""
    return load_settings_or_exit(Settings)
