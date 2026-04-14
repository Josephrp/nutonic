from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class SatelliteSettings:
    backend: str
    model_id: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    max_new_tokens: int
    torch_dtype: str


@lru_cache
def get_settings() -> SatelliteSettings:
    return SatelliteSettings(
        backend=os.environ.get("LFM_SATELLITE_BACKEND", "auto").strip().lower(),
        model_id=os.environ.get("LFM_SATELLITE_MODEL_ID", "LiquidAI/LFM2.5-VL-450M").strip(),
        openai_base_url=os.environ.get("LFM_SATELLITE_OPENAI_BASE_URL", "http://127.0.0.1:8001/v1")
        .strip()
        .rstrip("/"),
        openai_api_key=os.environ.get("LFM_SATELLITE_OPENAI_API_KEY", "dummy").strip(),
        openai_model=os.environ.get("LFM_SATELLITE_OPENAI_MODEL", "").strip()
        or os.environ.get("LFM_SATELLITE_MODEL_ID", "LiquidAI/LFM2.5-VL-450M").strip(),
        max_new_tokens=int(os.environ.get("LFM_SATELLITE_MAX_NEW_TOKENS", "256")),
        torch_dtype=os.environ.get("LFM_SATELLITE_TORCH_DTYPE", "bfloat16").strip().lower(),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
