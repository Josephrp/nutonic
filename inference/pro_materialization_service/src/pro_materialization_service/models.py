"""Request/response models — internal materialize API (`plans/2026-04-12-...` §5.1, §7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MaterializeRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    bbox_half_km: float = Field(default=5.0, gt=0, le=500.0)
    datetime_interval: str | None = Field(default=None, max_length=128)
    max_cloud_cover: float = Field(default=30.0, ge=0.0, le=100.0)
    stac_url: str = Field(default="https://earth-search.aws.element84.com/v1", max_length=512)
    collection_id: str = Field(default="sentinel-2-l2a", max_length=128)
    sentinel_fetch_mode: Literal["MINIMAL_RGB", "TERRAMIND_SPECTRAL", "FULL_STAC"] = "MINIMAL_RGB"
    analysis_profile: Literal[
        "wildfire",
        "oceanscout_ship_detection",
        "land_use_change",
        "flood_pulse",
        "brief_only",
    ] = "brief_only"
    mapbox_zoom: int = Field(default=12, ge=0, le=18)
    mapbox_bearing: float = Field(default=0.0)
    mapbox_pitch: float = Field(default=0.0)
    mapbox_size: int = Field(default=640, ge=64, le=1280)
    retina: bool = False
    vlm_contract_id: str = Field(default="nutonic.pro.vlm.v1_512", max_length=128)
    enable_tim: bool = False
    tim_branch: Literal["S2L2A_full", "RGB_mapbox"] = "RGB_mapbox"
    scene_id_t0: str | None = Field(default=None, max_length=256)
    scene_id_t1: str | None = Field(default=None, max_length=256)
    scene_id_t2: str | None = Field(default=None, max_length=256)


class VlmArtifact(BaseModel):
    role: str
    sha256: str
    mime: str
    width: int
    height: int
    inline_base64: str | None = None


class TimPayload(BaseModel):
    branch: str
    npz_base64: str | None = None
    modalities_keys: list[str] = Field(default_factory=list)


class MaterializeResult(BaseModel):
    materialization_id: str
    cache_key: str
    vlm_artifacts: list[VlmArtifact]
    tim_payload: TimPayload | None = None
    run_manifest: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- Legacy stub aliases (same pin fields; thin server may still call stub path) ---


class MaterializeStubIn(BaseModel):
    """Minimal pin for stub materialization."""

    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    tim_input_branch: str = Field(default="RGB_mapbox", max_length=64)


class MaterializeStubOut(BaseModel):
    """Subset of [MaterializeResult] for backward-compatible ``/materialize/stub``."""

    status: str = Field(default="ok")
    service: str = Field(default="pro_materialization_service")
    materialization_id: str
    latitude: float
    longitude: float
    tim_input_branch: str
    cache_key: str
    vlm_roles: list[str] = Field(default_factory=list)
    message: str = Field(default="Mapbox → VLM PNG (MINIMAL_RGB path).")
