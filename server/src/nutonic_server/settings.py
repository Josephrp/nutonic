from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `server/.env` (gitignored): optional local overrides; process env always wins.
# Repo-root `.env` is loaded first so `server/.env` can override shared keys (e.g. MAPBOX on worker only).
_SERVER_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _SERVER_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_SERVER_DIR / ".env"),
        ),
        env_file_encoding="utf-8",
    )

    leaderboard_database_url: str = Field(
        default="sqlite:///data/nutonic_leaderboard.db",
        validation_alias=AliasChoices(
            "NUTONIC_LEADERBOARD_DATABASE_URL",
            "LEADERBOARD_DATABASE_URL",
            "leaderboard_database_url",
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
    feature_ranked: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "FEATURE_RANKED",
            "NUTONIC_FEATURE_RANKED",
        ),
        description="When true, ranked round start/submit/forfeit routes are active (`IMP-090` / `IMP-091`).",
    )
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
        validation_alias=AliasChoices(
            "NUTONIC_RANKED_DATABASE_URL",
            "RANKED_DATABASE_URL",
            "ranked_database_url",
        ),
        description="SQLite (or SQLAlchemy URL) for ranked round rows (IMP-090).",
    )

    ranked_round_ttl_seconds: int = Field(
        default=900,
        validation_alias=AliasChoices("NUTONIC_RANKED_ROUND_TTL_SECONDS", "RANKED_ROUND_TTL_SECONDS"),
        description="TTL for round_ticket JWTs (seconds).",
    )

    ranked_stale_open_round_max_age_seconds: int = Field(
        default=604_800,
        validation_alias=AliasChoices(
            "NUTONIC_RANKED_STALE_OPEN_ROUND_MAX_AGE_SECONDS",
            "RANKED_STALE_OPEN_ROUND_MAX_AGE_SECONDS",
        ),
        description=(
            "Abandoned ``open`` ranked rounds older than this many seconds are deleted on the next "
            "``POST /api/v1/ranked/rounds/start`` (best-effort housekeeping)."
        ),
    )

    guess_telemetry_database_url: str = Field(
        default="sqlite:///data/nutonic_guess_telemetry.db",
        validation_alias=AliasChoices(
            "NUTONIC_GUESS_TELEMETRY_DATABASE_URL",
            "GUESS_TELEMETRY_DATABASE_URL",
            "guess_telemetry_database_url",
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

    pro_materialization_service_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NUTONIC_PRO_MATERIALIZATION_SERVICE_URL",
            "PRO_MATERIALIZATION_SERVICE_URL",
        ),
        description=(
            "Optional origin for the PRO materialization worker (`inference/pro_materialization_service`). "
            "When set alongside or instead of `inference_worker_base_url`, PRO job create probes "
            "GET `{origin}/health` for each configured origin (all must succeed for `inference_upstream_ok`)."
        ),
    )

    inference_hmac_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NUTONIC_INFERENCE_HMAC_SECRET",
            "INFERENCE_HMAC_SECRET",
        ),
        description=(
            "When non-empty, ``InferenceClient`` adds ``X-Nutonic-Timestamp``, ``X-Nutonic-Nonce``, "
            "and ``X-Nutonic-Signature`` (HMAC-SHA256 over a canonical line) to outbound worker ``GET`` "
            "requests such as health probes (IMP-092). Workers verify when deployed."
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

    manifest_full_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NUTONIC_MANIFEST_FULL_PATH", "MANIFEST_FULL_PATH"),
        description=(
            "Optional path to assembled manifest.full.json (same schema as GET /api/v1/cache/manifest when "
            "truth is exposed). When set and the file exists, replaces builtin demo catalog for maps/locations/ai."
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
