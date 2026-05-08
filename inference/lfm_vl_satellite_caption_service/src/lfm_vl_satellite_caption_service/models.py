from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SatelliteInferRequest(BaseModel):
    task: Literal["caption"] = "caption"
    image_base64: str = Field(..., min_length=1)
    ranked_clue_safe: bool = True
    prompt_template_version: str = "satellite-v1"
    analysis_profile: str | None = Field(default=None, max_length=128)
    contract_id: str | None = Field(default=None, max_length=128)


class SatelliteInferResponse(BaseModel):
    caption: str
    model_id: str = ""
    pipeline: str = "satellite_lfm_vl_specialist"
    analysis_profile: str | None = None
    contract_id: str | None = None
