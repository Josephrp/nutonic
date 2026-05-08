from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProJobProfile = Literal[
    "wildfire",
    "oceanscout_ship_detection",
    "land_use_change",
    "flood_pulse",
    "brief_only",
]


class ProJobCreateIn(BaseModel):
    center_lat: float = Field(ge=-90.0, le=90.0)
    center_lon: float = Field(ge=-180.0, le=180.0)
    bbox_half_km: float = Field(default=5.0, gt=0, le=500.0)
    mapbox_zoom: int = Field(default=12, ge=0, le=18)
    analysis_profile: ProJobProfile = Field(default="brief_only")
    enable_tim: bool = False
    tim_branch: Literal["S2L2A_full", "RGB_mapbox"] = "S2L2A_full"
    vlm_contract_id: str = Field(default="nutonic.pro.vlm.v1_512_s2_only", max_length=128)
    sentinel_fetch_mode: Literal["MINIMAL_RGB", "TERRAMIND_SPECTRAL", "FULL_STAC"] = "TERRAMIND_SPECTRAL"
    datetime_interval: str | None = Field(default=None, max_length=128)
    scene_id_t0: str | None = Field(default=None, max_length=256)
    scene_id_t1: str | None = Field(default=None, max_length=256)
    scene_id_t2: str | None = Field(default=None, max_length=256)


ProJobStatus = Literal["queued", "running", "completed", "failed", "cancelled", "cancelling"]


class ProArtifactRef(BaseModel):
    artifact_id: str = Field(max_length=128)
    sha256: str | None = Field(default=None, max_length=128)
    mime_type: str | None = Field(default=None, max_length=64)
    size_bytes: int | None = Field(default=None, ge=0)
    profile: str | None = Field(default=None, max_length=128)
    contract_id: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    required_for_profile: bool = False
    download_url: str | None = None


class ProBriefSection(BaseModel):
    title: str = Field(max_length=128)
    body: str = Field(max_length=2000)
    confidence: str | None = Field(default=None, max_length=64)


class ProVlmImageRef(BaseModel):
    role: str
    url: str | None = None
    inline_ref: str | None = None
    artifact_id: str | None = None
    width: int | None = None
    height: int | None = None
    mime: str | None = None


class ProOnDevicePayload(BaseModel):
    brief_sections: list[ProBriefSection] = Field(default_factory=list)
    overlay_refs: list[ProArtifactRef] = Field(default_factory=list)
    confidence_summary: str | None = Field(default=None, max_length=512)
    vlm_image_set: list[ProVlmImageRef] = Field(default_factory=list)
    vlm_prompt_injection: dict[str, Any] | None = None
    on_device_model_hint: str | None = Field(default=None, max_length=128)
    model_bundle_id: str | None = Field(default=None, max_length=128)


class ProJobStatusOut(BaseModel):
    job_id: str
    status: ProJobStatus
    status_reason: str | None = None
    error_class: str | None = None
    error_detail: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    profile: str | None = None
    analysis_profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    artifacts: list[ProArtifactRef] | None = None
    analysis_artifacts: list[ProArtifactRef] | None = None
    brief_artifacts: list[ProArtifactRef] | None = None
    scene_provenance: dict[str, Any] | None = None
    on_device_payload: ProOnDevicePayload | None = None
    bundle_download_url: str | None = None
    materialization_id: str | None = None
    cache_key: str | None = None
    materialization_summary: dict[str, Any] | None = None


class ProJobCreateOut(BaseModel):
    job_id: str
    status: ProJobStatus = "queued"


class ProVlmModelManifest(BaseModel):
    model_bundle_id: str
    revision: str
    download_url: str
    sha256: str
    size_bytes: int
    runtime: str
    min_app_version: str | None = None
    contract_ids: list[str] = Field(default_factory=list)


class ProVlmBoundingBox(BaseModel):
    label: str
    bbox: list[float] = Field(min_length=4, max_length=4)
    confidence: float | None = None


class ProVlmResult(BaseModel):
    caption: str
    boxes: list[ProVlmBoundingBox] = Field(default_factory=list)
    model_bundle_id: str | None = None
    revision: str | None = None
    source: str = "hf_space_vlm"

