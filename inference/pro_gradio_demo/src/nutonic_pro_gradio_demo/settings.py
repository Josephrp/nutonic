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

    inference_hmac_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NUTONIC_INFERENCE_HMAC_SECRET",
            "INFERENCE_HMAC_SECRET",
            "inference_hmac_secret",
        ),
        description=(
            "Shared HMAC secret for outbound calls to NU:TONIC services. When set, the client signs "
            "requests with X-Nutonic-Timestamp / X-Nutonic-Nonce / X-Nutonic-Content-SHA256 / "
            "X-Nutonic-Signature (same contract as tools/nutonic_hmac.py and server/inference_client.py)."
        ),
    )

    # Direct-worker fallback (workaround when game_server PRO jobs are degraded).
    pro_materialization_origin: str = Field(
        default="https://NuTonic-nutonic-pro-materialization.hf.space",
        validation_alias=AliasChoices("NUTONIC_PRO_MATERIALIZATION_ORIGIN", "pro_materialization_origin"),
    )
    lfm_brief_origin: str = Field(
        default="https://Tonic-nutonic-lfm-vl-streetview.hf.space",
        validation_alias=AliasChoices("NUTONIC_LFM_BRIEF_ORIGIN", "lfm_brief_origin"),
    )
    enable_direct_worker_fallback: bool = Field(
        default=True,
        validation_alias=AliasChoices("NUTONIC_ENABLE_DIRECT_WORKERS", "enable_direct_worker_fallback"),
        description="If true, bypass the game server and call workers directly when PRO jobs fail worker_unreachable.",
    )


def get_settings() -> Settings:
    return Settings()

