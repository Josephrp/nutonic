"""MVP HTTP surface for ``IMP-110`` — expand with real pano sampling."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="NU:TONIC Street View pano service", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/pano/metadata")
def pano_metadata(lat: float, lon: float) -> dict[str, object]:
    """Placeholder: return echo coordinates until Google/Mapillary integration lands."""
    return {"lat": lat, "lon": lon, "status": "stub", "pano_id": None}
