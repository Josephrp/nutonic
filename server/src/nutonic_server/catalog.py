"""Published map catalog shared by ``GET /api/v1/maps`` and ``GET /api/v1/cache/manifest`` (IMP-080)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from nutonic_server.catalog_generated import (
    CATALOG_MANIFEST_CONTENT_VERSION as _GEN_CV,
    CATALOG_MANIFEST_ENGINE_VERSION as _GEN_EV,
    MANIFEST_AI_GUESSES as _GEN_AI,
    MANIFEST_LOCATIONS as _GEN_LOCS,
    PUBLISHED_MAPS as _GEN_MAPS,
)
from nutonic_server.schemas import (
    AiGuessRowOut,
    CacheManifestOut,
    ManifestLocationOut,
    MapSummaryOut,
)

PUBLISHED_MAPS: list[MapSummaryOut] = list(_GEN_MAPS)
MANIFEST_LOCATIONS: list[ManifestLocationOut] = list(_GEN_LOCS)
MANIFEST_AI_GUESSES: list[AiGuessRowOut] = list(_GEN_AI)
CATALOG_MANIFEST_CONTENT_VERSION: str = _GEN_CV
CATALOG_MANIFEST_ENGINE_VERSION: str | None = _GEN_EV


def manifest_location_for_map(map_id: str) -> ManifestLocationOut | None:
    """First catalog round row for ``map_id`` (solo default)."""
    for loc in MANIFEST_LOCATIONS:
        if loc.map_id == map_id:
            return loc
    return None


def configure_catalog_from_manifest_path(path: str | None) -> None:
    """Replace in-process catalog from ``assemble_manifest`` JSON (mutates lists for stable imports)."""
    global CATALOG_MANIFEST_CONTENT_VERSION, CATALOG_MANIFEST_ENGINE_VERSION
    if path is None or not str(path).strip():
        return
    p = Path(path)
    if not p.is_file():
        warnings.warn(f"NUTONIC_MANIFEST_FULL_PATH set but not a file: {p}", stacklevel=2)
        return
    doc = CacheManifestOut.model_validate(json.loads(p.read_text(encoding="utf-8")))
    PUBLISHED_MAPS[:] = list(doc.maps)
    MANIFEST_LOCATIONS[:] = list(doc.locations)
    MANIFEST_AI_GUESSES[:] = list(doc.ai_guesses)
    CATALOG_MANIFEST_CONTENT_VERSION = doc.content_version
    CATALOG_MANIFEST_ENGINE_VERSION = doc.engine_version
