"""Pydantic DTOs for pano sampling API (``plans/2026-04-07-streetview-lfm-vl-hint-inference-plane`` §2.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CenterWgs84(BaseModel):
    lat: float
    lon: float


class PanosSampleRequest(BaseModel):
    request_id: str = Field(..., min_length=1)
    center: CenterWgs84
    count: int = Field(default=6, ge=1, le=24)
    radius_m: float = Field(default=120.0, ge=0.0, le=5000.0)
    heading_mode: str = Field(default="RADIAL_OR_RANDOM")
    image_width: int = Field(default=640, ge=32, le=2048)
    image_height: int = Field(default=640, ge=32, le=2048)


class PanoFrame(BaseModel):
    pano_id: str
    heading_deg: float
    pitch_deg: float = 0.0
    image_base64: str
    attribution: str = "© Stub (local dev — no Google imagery)"


class PanosSampleResponse(BaseModel):
    request_id: str
    frames: list[PanoFrame]
    cache_key: str
    terms_version: str = "2026-04"
