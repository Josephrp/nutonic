from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LeaderboardRowOut(BaseModel):
    display_handle: str
    player_role: str
    score_points: int
    distance_km: float | None = None


class LeaderboardPostIn(BaseModel):
    display_handle: str = Field(max_length=64)
    player_role: str = Field(max_length=32)
    score_points: int = Field(ge=0, le=1_000_000)
    distance_km: float | None = Field(default=None, ge=0.0, le=40_000.0)


class MapSummaryOut(BaseModel):
    """S1c catalog row (IMP-072); expand when manifests ship."""

    map_id: str
    title: str
    engine_version: str | None = None
    content_version: str | None = None


class UsefulHintsOut(BaseModel):
    tier_1: str | None = None
    tier_2: str | None = None
    tier_3: str | None = None
    tier_4: str | None = None
    tier_5: str | None = None
    tier_6: str | None = None


class StreetviewHintItemOut(BaseModel):
    """Pre-cached Street View assist line (no golden WGS84); matches ``docs/openapi.yaml``."""

    text: str
    viewpoint_id: str | None = None
    rank: int | None = None


class ManifestLocationOut(BaseModel):
    """Published round slice for non-ranked play (IMP-080 / IMP-081)."""

    model_config = ConfigDict(extra="ignore")

    map_id: str
    location_id: str
    truth_lat: float
    truth_lon: float
    ruleset_version: str | None = None
    still_bundle_id: str | None = Field(
        default=None,
        description="Versioned still id for GET /api/v1/bundles/{bundle_id} (IMP-081).",
    )
    still_bundled_resource: str | None = None
    still_http_url: str | None = None
    useful_hints: UsefulHintsOut | None = None
    streetview_hint_pack: list[StreetviewHintItemOut] | None = None
    streetview_assist_narrative: str | None = None
    satellite_caption_sidecar: dict[str, Any] | None = None
    play_budget_ms: int | None = None
    ai_marker_phase_enabled: bool = True


class AiGuessRowOut(BaseModel):
    """Fixture AI coordinates for catalog rounds (IMP-082)."""

    map_id: str
    location_id: str
    ai_lat: float
    ai_lon: float


class GuessRecordIn(BaseModel):
    round_instance_id: str = Field(max_length=512)
    location_id: str = Field(max_length=256)
    guess_lat: float = Field(ge=-90.0, le=90.0)
    guess_lon: float = Field(ge=-180.0, le=180.0)
    client_distance_km: float | None = Field(default=None, ge=0.0, le=40_000.0)
    ruleset_version: str | None = Field(default=None, max_length=128)


class GuessRecordOut(BaseModel):
    id: int
    recorded: bool = True


class RankedRoundStartIn(BaseModel):
    map_id: str = Field(max_length=256)


class RankedClueOut(BaseModel):
    """Redacted ranked clue: no golden coordinates."""

    map_id: str
    location_id: str
    still_bundle_id: str | None = None
    still_bundled_resource: str | None = None
    useful_hints: UsefulHintsOut | None = None
    streetview_hint_pack: list[StreetviewHintItemOut] | None = None
    streetview_assist_narrative: str | None = None
    satellite_caption_sidecar: dict[str, Any] | None = None
    play_budget_ms: int | None = None
    ai_marker_phase_enabled: bool = True


class RankedRoundStartOut(BaseModel):
    round_id: str
    round_ticket: str
    expires_in: int
    clue: RankedClueOut


class RankedSubmitIn(BaseModel):
    guess_lat: float = Field(ge=-90.0, le=90.0)
    guess_lon: float = Field(ge=-180.0, le=180.0)
    round_ticket: str


class RankedSubmitOut(BaseModel):
    distance_km: float
    score_points: int
    verified: bool = True


class RankedForfeitIn(BaseModel):
    """Server-attested ranked integrity forfeit (`docs/RANKED-MODE.md` §4, IMP-091)."""

    reason: Literal["peer_reveal", "assists"]


class RankedForfeitOut(BaseModel):
    ok: bool = True
    status: str = "forfeited"


ProJobProfile = Literal[
    "wildfire",
    "oceanscout_ship_detection",
    "land_use_change",
    "flood_pulse",
    "brief_only",
]
ProJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ProArtifactRef(BaseModel):
    artifact_id: str = Field(max_length=128)
    kind: str = Field(max_length=64)
    mime_type: str = Field(max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    profile: str | None = Field(default=None, max_length=128)
    download_url: str | None = None


class ProBriefSection(BaseModel):
    title: str = Field(max_length=128)
    body: str = Field(max_length=2000)
    confidence: str | None = Field(default=None, max_length=64)


class ProOnDevicePayload(BaseModel):
    brief_sections: list[ProBriefSection] = Field(default_factory=list)
    overlay_refs: list[ProArtifactRef] = Field(default_factory=list)
    confidence_summary: str | None = Field(default=None, max_length=512)


class ProJobCreateIn(BaseModel):
    center_lat: float = Field(ge=-90.0, le=90.0)
    center_lon: float = Field(ge=-180.0, le=180.0)
    bbox_half_km: float = Field(default=5.0, gt=0, le=500.0)
    mapbox_zoom: int = Field(default=12, ge=0, le=18)
    analysis_profile: ProJobProfile = Field(
        default="brief_only",
        description="Mini-app analysis profile. Legacy vessel_monitoring requests are normalized to OceanScout.",
    )
    enable_tim: bool = False
    tim_branch: Literal["S2L2A_full", "RGB_mapbox"] = "RGB_mapbox"
    vlm_contract_id: str = Field(default="nutonic.pro.vlm.v1_512", max_length=128)
    sentinel_fetch_mode: Literal["MINIMAL_RGB", "TERRAMIND_SPECTRAL", "FULL_STAC"] = "MINIMAL_RGB"
    datetime_interval: str | None = Field(default=None, max_length=128)
    scene_id_t0: str | None = Field(default=None, max_length=256)
    scene_id_t1: str | None = Field(default=None, max_length=256)

    @field_validator("analysis_profile", mode="before")
    @classmethod
    def normalize_analysis_profile(cls, v: object) -> object:
        if str(v).strip() == "vessel_monitoring":
            return "oceanscout_ship_detection"
        return v


class ProJobCreateOut(BaseModel):
    job_id: str
    status: ProJobStatus = "queued"
    inference_upstream_ok: bool | None = Field(
        default=None,
        description=(
            "Compatibility field from the old synchronous create response. "
            "Async jobs now report worker health through status/error_class while polling."
        ),
    )
    materialization_ok: bool | None = Field(
        default=None,
        description=(
            "Compatibility field from the old synchronous create response. "
            "Async jobs now expose materialization outcome on the status resource."
        ),
    )
    materialization_id: str | None = Field(default=None, description="Compatibility materialization worker id.")
    cache_key: str | None = Field(default=None, description="Compatibility materialization cache key.")
    materialization_error: str | None = Field(
        default=None,
        description="Compatibility materialization error text; new clients should prefer status/error fields.",
    )


class ProJobStatusOut(BaseModel):
    job_id: str
    status: ProJobStatus
    status_reason: str | None = None
    error_class: str | None = None
    error_detail: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    profile: str | None = Field(default=None, description="Compatibility alias for analysis_profile.")
    analysis_profile: str | None = Field(default=None, description="Canonical mini-app analysis profile token.")
    started_at: str | None = None
    finished_at: str | None = None
    artifacts: list[ProArtifactRef] | None = None
    analysis_artifacts: list[ProArtifactRef] | None = None
    brief_artifacts: list[ProArtifactRef] | None = None
    scene_provenance: dict[str, Any] | None = None
    on_device_payload: ProOnDevicePayload | None = Field(
        default=None,
        description="Compact brief/overlay payload intended for client mini-app handoff.",
    )
    bundle_download_url: str | None = Field(
        default=None,
        description="Compatibility field; artifact refs are preferred for new clients.",
    )
    materialization_id: str | None = Field(default=None, description="Compatibility materialization worker id.")
    cache_key: str | None = Field(default=None, description="Compatibility materialization cache key.")
    materialization_summary: dict[str, Any] | None = None


class ProJobCancelOut(BaseModel):
    ok: bool = True
    status: str


class CacheManifestOut(BaseModel):
    """Hydration manifest for clients (`rules/13`, IMP-080). Catalog mirrors ``GET /api/v1/maps``."""

    content_version: str
    engine_version: str | None = None
    maps: list[MapSummaryOut]
    locations: list[ManifestLocationOut] = Field(default_factory=list)
    ai_guesses: list[AiGuessRowOut] = Field(default_factory=list)
