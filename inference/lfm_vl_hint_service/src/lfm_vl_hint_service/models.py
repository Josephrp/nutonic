"""Request/response DTOs for ``POST /v1/suggestions/from_frames``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HintFrame(BaseModel):
    image_base64: str = Field(..., min_length=1)
    pano_id: str | None = None
    heading_deg: float | None = None
    pitch_deg: float | None = None


class SuggestionsFromFramesRequest(BaseModel):
    frames: list[HintFrame] = Field(..., min_length=1)
    ranked_clue_safe: bool = True
    prompt_template_version: str = "stub-v1"
    useful_hints: dict[str, Any] | None = None
    mission_flavor: str | None = None


class SuggestionItem(BaseModel):
    text: str
    viewpoint_id: str
    rank: int = Field(ge=1)


class SuggestionsFromFramesResponse(BaseModel):
    suggestions: list[SuggestionItem]
