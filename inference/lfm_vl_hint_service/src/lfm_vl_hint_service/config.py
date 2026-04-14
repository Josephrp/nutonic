"""Runtime configuration (env-driven) for LFM-VL hint inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class LfmVlSettings:
    """See ``README.md`` for operator matrix."""

    backend: str  # stub | transformers | openai_compatible
    model_id: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    max_new_tokens: int
    torch_dtype: str  # auto | bfloat16 | float16 | float32


@lru_cache
def get_settings() -> LfmVlSettings:
    backend = os.environ.get("LFM_VL_BACKEND", "auto").strip().lower()
    if backend in ("0", "false", "no"):
        backend = "stub"
    return LfmVlSettings(
        backend=backend,
        model_id=os.environ.get("LFM_VL_MODEL_ID", "LiquidAI/LFM2.5-VL-450M").strip(),
        openai_base_url=os.environ.get("LFM_OPENAI_BASE_URL", "http://127.0.0.1:8000/v1").strip().rstrip("/"),
        openai_api_key=os.environ.get("LFM_OPENAI_API_KEY", "dummy").strip(),
        openai_model=os.environ.get("LFM_OPENAI_MODEL", "").strip() or os.environ.get(
            "LFM_VL_MODEL_ID", "LiquidAI/LFM2.5-VL-450M"
        ).strip(),
        max_new_tokens=int(os.environ.get("LFM_VL_MAX_NEW_TOKENS", "256")),
        torch_dtype=os.environ.get("LFM_VL_TORCH_DTYPE", "bfloat16").strip().lower(),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
