"""Street View provider selection (Google Static API vs local stub)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class PanoServiceSettings:
    provider: str  # auto | google | stub
    google_maps_api_key: str


@lru_cache
def get_pano_settings() -> PanoServiceSettings:
    prov = os.environ.get("STREETVIEW_PROVIDER", "auto").strip().lower()
    key = (os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_STREETVIEW_API_KEY") or "").strip()
    if prov == "auto":
        prov = "google" if key else "stub"
    return PanoServiceSettings(provider=prov, google_maps_api_key=key)


def reset_pano_settings_cache() -> None:
    get_pano_settings.cache_clear()
