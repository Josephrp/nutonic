"""Load ``s2_asset_mapping_version`` and optional per-band STAC key order from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from pro_materialization_service.geospatial.s2_stac_load import EARTH_SEARCH_S2L2A_ASSET_KEYS


def _allowlist_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "s2_asset_allowlist.yaml"


def s2_asset_mapping_version() -> str:
    """Return version string for health checks and cache keys."""
    raw = _allowlist_path().read_bytes()
    doc = yaml.safe_load(raw)
    if isinstance(doc, dict) and isinstance(doc.get("version"), str):
        return str(doc["version"])
    return "unknown"


def s2_band_asset_keys() -> tuple[str, ...]:
    """12 STAC asset id preferences (TerraMind channel order); falls back to Earth Search defaults."""
    doc = yaml.safe_load(_allowlist_path().read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return EARTH_SEARCH_S2L2A_ASSET_KEYS
    assets = doc.get("assets")
    if isinstance(assets, list) and len(assets) == 12:
        return tuple(str(x) for x in assets)
    return EARTH_SEARCH_S2L2A_ASSET_KEYS
