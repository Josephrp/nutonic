"""Resolve ``map_id`` / truth from whatever is baked into ``catalog_generated.py`` (demo or shipped)."""

from __future__ import annotations

from nutonic_server import catalog as game_catalog


def sample_map_id() -> str:
    """First published map id (stable for ranked / leaderboard URL tests)."""
    if not game_catalog.PUBLISHED_MAPS:
        return "demo"
    return str(game_catalog.PUBLISHED_MAPS[0].map_id)


def manifest_location_for_sample_map():
    """First ``ManifestLocationOut`` for ``sample_map_id()``."""
    mid = sample_map_id()
    loc = game_catalog.manifest_location_for_map(mid)
    if loc is None:
        raise AssertionError(f"No MANIFEST_LOCATIONS row for map_id={mid!r}")
    return loc


def truth_coordinates_for_map(map_id: str) -> tuple[float, float]:
    loc = game_catalog.manifest_location_for_map(map_id)
    if loc is None:
        raise AssertionError(f"No manifest location for map_id={map_id!r}")
    return (float(loc.truth_lat), float(loc.truth_lon))
