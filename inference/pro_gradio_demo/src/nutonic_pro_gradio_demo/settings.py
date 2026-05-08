from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    nutonic_server_origin: str = Field(
        default="",
        validation_alias=AliasChoices("NUTONIC_SERVER_ORIGIN", "nutonic_server_origin"),
        description="Base origin for the game server (e.g. https://NuTonic/nutonic-game-server.hf.space).",
    )

    require_server_origin: bool = Field(
        default=True,
        validation_alias=AliasChoices("NUTONIC_REQUIRE_SERVER_ORIGIN", "require_server_origin"),
        description="When true, the Gradio UI fails fast if NUTONIC_SERVER_ORIGIN is unset.",
    )

    http_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("NUTONIC_HTTP_TIMEOUT_SECONDS", "http_timeout_seconds"),
    )

    poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("NUTONIC_PRO_POLL_INTERVAL_SECONDS", "poll_interval_seconds"),
    )

    poll_timeout_seconds: float = Field(
        default=240.0,
        validation_alias=AliasChoices("NUTONIC_PRO_POLL_TIMEOUT_SECONDS", "poll_timeout_seconds"),
    )

    model_cache_dir: str = Field(
        default="",
        validation_alias=AliasChoices("NUTONIC_VLM_CACHE_DIR", "model_cache_dir"),
        description="Writable directory for cached model weights; empty means choose a default at runtime.",
    )


def get_settings() -> Settings:
    return Settings()

