from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `server/.env` (gitignored): optional local overrides; process env always wins.
# Repo-root `.env` is loaded first so `server/.env` can override shared keys (e.g. MAPBOX on worker only).
_SERVER_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _SERVER_DIR.parent

# PRO on-device VLM: default ``model.safetensors`` from ``NuTonic/lspace`` (pin matches Hub commit on ``main``).
_DEFAULT_PRO_VLM_MODEL_DOWNLOAD_URL = (
    "https://huggingface.co/NuTonic/lspace/resolve/"
    "3ec756bfc8a94fcb23801fe6925d832ab35595f2/model.safetensors"
)
_DEFAULT_PRO_VLM_MODEL_SHA256 = (
    "7e9ae0b2225c8755eb68924aa97f81c0826678f77f7832aa81c8398f5439cf5c"
)
_DEFAULT_PRO_VLM_MODEL_SIZE_BYTES = 897_484_568
_DEFAULT_PRO_VLM_MODEL_REVISION = "3ec756bfc8a94fcb23801fe6925d832ab35595f2"
_DEFAULT_PRO_VLM_MODEL_BUNDLE_ID = "NuTonic/lspace"


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
    # Safer internet-facing defaults: ranked/pro off until routes ship. Community LB POST defaults on so local
    # `uvicorn` matches `.env.example`; production profiles set FEATURE_COMMUNITY_LB_POST=false explicitly.
    feature_ranked: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "FEATURE_RANKED",
            "NUTONIC_FEATURE_RANKED",
        ),
        description="When true, ranked round start/submit/forfeit routes are active (`IMP-090` / `IMP-091`).",
    )
    feature_community_lb_get: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FEATURE_COMMUNITY_LB_GET",
            "NUTONIC_FEATURE_COMMUNITY_LB_GET",
        ),
        description="When false, community leaderboard GET returns 403 (`features.community_lb_get`).",
    )
    feature_community_lb_post: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FEATURE_COMMUNITY_LB_POST",
            "NUTONIC_FEATURE_COMMUNITY_LB_POST",
        ),
        description=(
            "When false, community leaderboard POST returns 403 (`features.community_lb_post`). "
            "Set false on internet-facing hosts that should not accept lab aggregate writes."
        ),
    )
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
            "PRO jobs probe configured origins before execution; origins listed in `pro_required_origins` "
            "must succeed, while `pro_optional_origins` may be degraded without failing the job."
        ),
    )

    lfm_vl_hint_service_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NUTONIC_LFM_VL_HINT_SERVICE_URL",
            "LFM_VL_HINT_SERVICE_URL",
        ),
        description=(
            "Optional origin for the LFM-VL hint/brief service. When set, PRO jobs can call "
            "`POST {origin}/v1/pro/brief/fuse` after materialization."
        ),
    )

    pro_job_backend: str = Field(
        default="sqlite",
        validation_alias=AliasChoices("NUTONIC_PRO_JOB_BACKEND", "PRO_JOB_BACKEND"),
        description="PRO job persistence backend. Only `sqlite` is implemented today.",
    )

    pro_job_database_url: str = Field(
        default="sqlite:///data/nutonic_pro_jobs.db",
        validation_alias=AliasChoices("NUTONIC_PRO_JOB_DATABASE_URL", "PRO_JOB_DATABASE_URL"),
        description="SQLAlchemy URL for persisted PRO job status and artifact metadata.",
    )

    pro_required_origins: str = Field(
        default="pro_materialization",
        validation_alias=AliasChoices("NUTONIC_PRO_REQUIRED_ORIGINS", "PRO_REQUIRED_ORIGINS"),
        description="Comma-separated PRO origin names that must pass health probes before a job runs.",
    )

    pro_optional_origins: str = Field(
        default="inference_worker",
        validation_alias=AliasChoices("NUTONIC_PRO_OPTIONAL_ORIGINS", "PRO_OPTIONAL_ORIGINS"),
        description="Comma-separated PRO origin names that may be degraded without failing the job.",
    )

    pro_job_ttl_seconds: int = Field(
        default=86_400,
        validation_alias=AliasChoices("NUTONIC_PRO_JOB_TTL_SECONDS", "PRO_JOB_TTL_SECONDS"),
        description="Retention window for terminal PRO jobs and their artifacts.",
    )

    pro_max_concurrent_jobs: int = Field(
        default=2,
        validation_alias=AliasChoices("NUTONIC_PRO_MAX_CONCURRENT_JOBS", "PRO_MAX_CONCURRENT_JOBS"),
        description="Maximum number of concurrently running in-process PRO jobs.",
    )

    pro_job_poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("NUTONIC_PRO_JOB_POLL_INTERVAL_SECONDS", "PRO_JOB_POLL_INTERVAL_SECONDS"),
        description="Default server-side PRO runner poll interval for future queue sweepers.",
    )

    pro_artifact_root: str = Field(
        default="data/pro_artifacts",
        validation_alias=AliasChoices("NUTONIC_PRO_ARTIFACT_ROOT", "PRO_ARTIFACT_ROOT"),
        description="Filesystem root for PRO job artifact bytes.",
    )

    pro_vlm_model_bundle_id: str = Field(
        default=_DEFAULT_PRO_VLM_MODEL_BUNDLE_ID,
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_BUNDLE_ID", "PRO_VLM_MODEL_BUNDLE_ID"),
        description="Published on-device PRO VLM model bundle id advertised to clients.",
    )

    pro_vlm_model_revision: str = Field(
        default=_DEFAULT_PRO_VLM_MODEL_REVISION,
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_REVISION", "PRO_VLM_MODEL_REVISION"),
        description="Revision/version for the published on-device PRO VLM model.",
    )

    pro_vlm_model_download_url: str = Field(
        default=_DEFAULT_PRO_VLM_MODEL_DOWNLOAD_URL,
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_DOWNLOAD_URL", "PRO_VLM_MODEL_DOWNLOAD_URL"),
        description=(
            "HTTPS URL for the VLM artifact (game CDN or Hugging Face `/resolve/…` for dev). "
            "Clients omit Nutonic auth when the host differs from the game server."
        ),
    )

    pro_vlm_model_local_path: str = Field(
        default="",
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_LOCAL_PATH", "PRO_VLM_MODEL_LOCAL_PATH"),
        description=(
            "Optional path to a model bundle baked into the game-server image at publish time. "
            "When set, /api/v1/pro/vlm/model-manifest derives size/sha256 from this file."
        ),
    )

    pro_vlm_model_sha256: str = Field(
        default=_DEFAULT_PRO_VLM_MODEL_SHA256,
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_SHA256", "PRO_VLM_MODEL_SHA256"),
        description="Lowercase hex sha256 for the model artifact; clients verify before use.",
    )

    pro_vlm_model_size_bytes: int = Field(
        default=_DEFAULT_PRO_VLM_MODEL_SIZE_BYTES,
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_SIZE_BYTES", "PRO_VLM_MODEL_SIZE_BYTES"),
        description="Expected model artifact size in bytes.",
    )

    pro_vlm_model_runtime: str = Field(
        default="leap",
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_RUNTIME", "PRO_VLM_MODEL_RUNTIME"),
        description="Client runtime hint, e.g. leap, coreml, onnx, or webgpu.",
    )

    pro_vlm_model_contract_ids: str = Field(
        default="nutonic.pro.vlm.v1_512_s2_only",
        validation_alias=AliasChoices("NUTONIC_PRO_VLM_MODEL_CONTRACT_IDS", "PRO_VLM_MODEL_CONTRACT_IDS"),
        description="Comma-separated VLM image contract ids supported by the advertised model bundle.",
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

    hf_persistence_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("NUTONIC_HF_PERSISTENCE_ENABLED", "HF_PERSISTENCE_ENABLED"),
        description="When true, mirror SQLite server DB files to a Hugging Face Dataset repo.",
    )

    hf_persistence_required: bool = Field(
        default=False,
        validation_alias=AliasChoices("NUTONIC_HF_PERSISTENCE_REQUIRED", "HF_PERSISTENCE_REQUIRED"),
        description=(
            "When true with HF persistence enabled, fail fast if the dataset repo/token is missing "
            "or sync operations fail."
        ),
    )

    hf_persistence_repo_id: str = Field(
        default="",
        validation_alias=AliasChoices("NUTONIC_HF_PERSISTENCE_REPO_ID", "HF_PERSISTENCE_REPO_ID"),
        description="Dataset repo id (owner/name) used for SQLite persistence mirroring.",
    )

    hf_persistence_dataset_subdir: str = Field(
        default="server-persistence",
        validation_alias=AliasChoices("NUTONIC_HF_PERSISTENCE_SUBDIR", "HF_PERSISTENCE_SUBDIR"),
        description="Subdirectory inside the Dataset repo where DB files are stored.",
    )

    hf_persistence_startup_pull_mode: str = Field(
        default="if_missing",
        validation_alias=AliasChoices(
            "NUTONIC_HF_PERSISTENCE_STARTUP_PULL_MODE",
            "HF_PERSISTENCE_STARTUP_PULL_MODE",
        ),
        description="Startup pull policy for local SQLite files: if_missing (default) or always.",
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

    def pro_required_origin_names(self) -> list[str]:
        return _split_csv(self.pro_required_origins)

    def pro_optional_origin_names(self) -> list[str]:
        return _split_csv(self.pro_optional_origins)

    def pro_vlm_model_contract_id_list(self) -> list[str]:
        return _split_csv(self.pro_vlm_model_contract_ids)

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


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
