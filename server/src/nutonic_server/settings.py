from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `server/.env` (gitignored): optional local overrides; process env always wins.
_SERVER_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        populate_by_name=True,
        env_file=_SERVER_DIR / ".env",
        env_file_encoding="utf-8",
    )

    leaderboard_database_url: str = Field(
        default="sqlite:///data/nutonic_leaderboard.db",
        validation_alias=AliasChoices(
            "NUTONIC_LEADERBOARD_DATABASE_URL",
            "LEADERBOARD_DATABASE_URL",
        ),
        description=(
            "SQLAlchemy URL for community leaderboard persistence (IMP-060). "
            "Use sqlite+pysqlite:///:memory: for ephemeral dev; tests default to in-memory."
        ),
    )

    cors_origins: str = ""
    """Comma-separated allowed origins for browser clients; empty disables CORS middleware."""

    # Runtime feature toggles (IMP-001); map to GET /api/v1/config → features.*
    # Safer internet-facing defaults: ranked/pro until routes ship; POST off unless explicitly enabled.
    feature_ranked: bool = False
    feature_community_lb_get: bool = True
    feature_community_lb_post: bool = False
    feature_pro_jobs: bool = False

    feature_guesses_record: bool = Field(
        default=False,
        validation_alias=AliasChoices("NUTONIC_FEATURE_GUESSES_RECORD", "FEATURE_GUESSES_RECORD"),
        description="When true, allow POST /api/v1/maps/{map_id}/guesses/record (non-authoritative telemetry).",
    )

    ranked_database_url: str = Field(
        default="sqlite:///data/nutonic_ranked.db",
        validation_alias=AliasChoices("NUTONIC_RANKED_DATABASE_URL", "RANKED_DATABASE_URL"),
        description="SQLite (or SQLAlchemy URL) for ranked round rows (IMP-090).",
    )

    ranked_round_ttl_seconds: int = Field(
        default=900,
        validation_alias=AliasChoices("NUTONIC_RANKED_ROUND_TTL_SECONDS", "RANKED_ROUND_TTL_SECONDS"),
        description="TTL for round_ticket JWTs (seconds).",
    )

    guess_telemetry_database_url: str = Field(
        default="sqlite:///data/nutonic_guess_telemetry.db",
        validation_alias=AliasChoices(
            "NUTONIC_GUESS_TELEMETRY_DATABASE_URL",
            "GUESS_TELEMETRY_DATABASE_URL",
        ),
        description="SQLite URL for optional guess telemetry rows.",
    )

    enable_ops_gradio: bool = Field(
        default=False,
        validation_alias=AliasChoices("NUTONIC_ENABLE_OPS_GRADIO", "ENABLE_OPS_GRADIO"),
        description="Mount read-only Gradio /ops when gradio extra is installed (IMP-101).",
    )

    inference_worker_base_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NUTONIC_INFERENCE_WORKER_BASE_URL",
            "INFERENCE_WORKER_BASE_URL",
        ),
        description=(
            "Optional origin for IMP-092 probes (e.g. `http://streetview_pano_service:7860`). "
            "When set, PRO job create performs GET `{base}/health` via InferenceClient."
        ),
    )

    expose_manifest_round_truth: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH",
            "EXPOSE_MANIFEST_ROUND_TRUTH",
        ),
        description=(
            "When false, GET /api/v1/cache/manifest omits `locations` and `ai_guesses` (spoiler hygiene for "
            "world-readable manifests). Set true for local dev / CI fixtures that assert full catalog slices."
        ),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def strip_origins(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    def cors_origin_list(self) -> list[str]:
        if not self.cors_origins:
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    jwt_secret: str = Field(
        default="dev-only-change-in-production-min-32b!!",
        validation_alias=AliasChoices("NUTONIC_JWT_SECRET", "JWT_SECRET"),
        description=(
            "HS256 signing key for anonymous session JWTs (IMP-030). Override in any shared or production deploy."
        ),
    )

    jwt_ttl_seconds: int = 3600
    """Access token lifetime in seconds."""


def load_settings() -> Settings:
    return Settings()
