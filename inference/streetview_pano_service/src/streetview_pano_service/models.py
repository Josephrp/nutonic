"""Pydantic DTOs for pano sampling API (``plans/2026-04-07-streetview-lfm-vl-hint-inference-plane`` §2.2)."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SamplingMode = Literal["STOCHASTIC_S2_FOOTPRINT", "LEGACY_RADIAL_OFFSET", "OMNI_SINGLE_PANO"]


class CenterWgs84(BaseModel):
    lat: float
    lon: float


class PanosSampleRequest(BaseModel):
    request_id: str = Field(..., min_length=1)
    center: CenterWgs84
    count: int = Field(default=6, ge=1, le=24)
    sampling_mode: SamplingMode = Field(
        default="STOCHASTIC_S2_FOOTPRINT",
        description="STOCHASTIC_S2_FOOTPRINT (default): seeded random anchors in disk R. "
        "LEGACY_RADIAL_OFFSET: pre-2026 radial offsets + spaced headings. "
        "OMNI_SINGLE_PANO: one center pano, headings i·360/N.",
    )
    heading_mode: str | None = Field(
        default=None,
        description="Deprecated. If RADIAL_OR_RANDOM and sampling_mode omitted, maps to LEGACY_RADIAL_OFFSET.",
    )
    radius_m: float = Field(
        default=120.0,
        ge=0.0,
        le=5000.0,
        description="Legacy only: radial offset cap for LEGACY_RADIAL_OFFSET.",
    )
    area_radius_m: float | None = Field(
        default=None,
        description="Disk radius R (m). None → server default from S2 chip policy (capped). Must be > 0 when set.",
    )
    jitter_seed: int | None = Field(
        default=None,
        description="RNG seed for stochastic anchors/headings. None → SHA-256(request_id) first 8 hex.",
    )
    min_anchor_separation_m: float | None = Field(
        default=None,
        ge=0.0,
        description="Reject anchor if closer than this (haversine) to an already accepted anchor.",
    )
    fov_deg: int | None = Field(default=None, ge=10, le=120, description="Static API FOV; default 75.")
    pitch_jitter_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=45.0,
        description="If set, pitch per frame is uniform in [-jitter, +jitter] (stochastic/omni).",
    )
    image_width: int = Field(default=640, ge=32, le=2048)
    image_height: int = Field(default=640, ge=32, le=2048)

    @model_validator(mode="before")
    @classmethod
    def _legacy_heading_mode(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("sampling_mode") is not None:
            return data
        hm = data.get("heading_mode")
        if hm == "RADIAL_OR_RANDOM":
            data["sampling_mode"] = "LEGACY_RADIAL_OFFSET"
        elif hm in ("OMNI", "OMNI_SINGLE_PANO"):
            data["sampling_mode"] = "OMNI_SINGLE_PANO"
        return data

    @field_validator("area_radius_m")
    @classmethod
    def _validate_area_radius(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("area_radius_m must be positive when set")
        return v


def resolve_jitter_seed(request_id: str, explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit) & 0xFFFFFFFFFFFFFFFF
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


class PanoFrame(BaseModel):
    pano_id: str
    heading_deg: float
    pitch_deg: float = 0.0
    image_base64: str
    attribution: str = "© Stub (local dev — no Google imagery)"
    anchor_lat: float | None = Field(default=None, description="Set only when sampling debug is enabled.")
    anchor_lon: float | None = Field(default=None, description="Set only when sampling debug is enabled.")


class PanosSampleResponse(BaseModel):
    request_id: str
    frames: list[PanoFrame]
    cache_key: str
    terms_version: str = "2026-04"
    sampling_debug: dict[str, Any] | None = Field(
        default=None,
        description="Present when STREETVIEW_EXPOSE_SAMPLING_DEBUG=1; no secrets.",
    )
