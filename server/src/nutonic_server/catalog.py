"""Published map catalog shared by ``GET /api/v1/maps`` and ``GET /api/v1/cache/manifest`` (IMP-080)."""

from __future__ import annotations

from nutonic_server.schemas import (
    AiGuessRowOut,
    ManifestLocationOut,
    MapSummaryOut,
    UsefulHintsOut,
)

PUBLISHED_MAPS: list[MapSummaryOut] = [
    MapSummaryOut(
        map_id="demo",
        title="Demo mission",
        engine_version="0.1.0",
        content_version=None,
    ),
    MapSummaryOut(
        map_id="idempotency-map",
        title="Lab · idempotency fixture",
        engine_version="0.1.0",
        content_version=None,
    ),
]

# Default SCAN round fixtures + AI rows (IMP-081 canned still path, IMP-082 AiGuessStore stub).
MANIFEST_LOCATIONS: list[ManifestLocationOut] = [
    ManifestLocationOut(
        map_id="demo",
        location_id="demo-vienna-001",
        truth_lat=48.2082,
        truth_lon=16.3738,
        ruleset_version="nutonic.ruleset.v1",
        still_bundle_id="nutonic.bundle.v1.demo_still",
        still_bundled_resource="files/3.jpg",
        useful_hints=UsefulHintsOut(
            tier_1="Western edge of the Eurasian landmass near Atlantic influence.",
            tier_2="Alpine foothill capital on a major river north-east of high peaks.",
            tier_3="Austria · Vienna metro region.",
        ),
        play_budget_ms=180_000,
        ai_marker_phase_enabled=True,
    ),
    ManifestLocationOut(
        map_id="idempotency-map",
        location_id="idempo-nyc-001",
        truth_lat=40.7128,
        truth_lon=-74.0060,
        ruleset_version="nutonic.ruleset.v1",
        still_bundle_id="nutonic.bundle.v1.demo_still",
        still_bundled_resource="files/3.jpg",
        useful_hints=UsefulHintsOut(
            tier_1="Eastern North American coastal megacity region.",
            tier_2="Compact island grid between two tidal rivers.",
            tier_3="USA · New York City.",
        ),
        play_budget_ms=180_000,
        ai_marker_phase_enabled=True,
    ),
]

def manifest_location_for_map(map_id: str) -> ManifestLocationOut | None:
    """First catalog round row for ``map_id`` (solo default)."""
    for loc in MANIFEST_LOCATIONS:
        if loc.map_id == map_id:
            return loc
    return None


MANIFEST_AI_GUESSES: list[AiGuessRowOut] = [
    AiGuessRowOut(map_id="demo", location_id="demo-vienna-001", ai_lat=41.9028, ai_lon=12.4964),
    AiGuessRowOut(map_id="idempotency-map", location_id="idempo-nyc-001", ai_lat=51.5074, ai_lon=-0.1278),
]
