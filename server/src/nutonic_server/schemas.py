from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class ProJobCreateIn(BaseModel):
    center_lat: float = Field(ge=-90.0, le=90.0)
    center_lon: float = Field(ge=-180.0, le=180.0)


class ProJobCreateOut(BaseModel):
    job_id: str
    status: str = "queued"
    inference_upstream_ok: bool | None = None


class ProJobStatusOut(BaseModel):
    job_id: str
    status: str
    bundle_download_url: str | None = None


class CacheManifestOut(BaseModel):
    """Hydration manifest for clients (`rules/13`, IMP-080). Catalog mirrors ``GET /api/v1/maps``."""

    content_version: str
    engine_version: str | None = None
    maps: list[MapSummaryOut]
    locations: list[ManifestLocationOut] = Field(default_factory=list)
    ai_guesses: list[AiGuessRowOut] = Field(default_factory=list)
