"""Event catalog loading and simple geospatial sampling for PRO datasets."""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geo_nutonic import haversine_km


@dataclass
class GeoEvent:
    event_id: str
    lat: float
    lon: float
    event_date: str
    profile: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _to_event(row: dict[str, Any], *, profile: str, source: str, idx: int) -> GeoEvent:
    event_id = str(row.get("event_id") or row.get("id") or f"{profile}_{idx:06d}")
    lat = float(row.get("lat", row.get("latitude")))
    lon = float(row.get("lon", row.get("longitude")))
    event_date = str(row.get("event_date") or row.get("date") or row.get("datetime") or "")
    metadata = {k: v for k, v in row.items() if k not in {"event_id", "id", "lat", "latitude", "lon", "longitude", "event_date", "date", "datetime"}}
    return GeoEvent(
        event_id=event_id,
        lat=lat,
        lon=lon,
        event_date=event_date,
        profile=profile,
        source=source,
        metadata=metadata,
    )


def _load_table(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(x) for x in data]
        raise ValueError(f"Expected JSON array in {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_events_file(path: Path, *, profile: str, source: str) -> list[GeoEvent]:
    rows = _load_table(path)
    out: list[GeoEvent] = []
    for i, row in enumerate(rows):
        try:
            out.append(_to_event(row, profile=profile, source=source, idx=i))
        except Exception:
            continue
    return out


def load_fire_events(source: str = "manual", path: Path | None = None) -> list[GeoEvent]:
    if path is None:
        return []
    return load_events_file(path, profile="wildfire", source=source)


def load_flood_events(source: str = "manual", path: Path | None = None) -> list[GeoEvent]:
    if path is None:
        return []
    return load_events_file(path, profile="flood", source=source)


def default_oceanscout_pois_path(repo_root: Path) -> Path:
    return repo_root / "data" / "events" / "oceanscout_pois.json"


def default_landshift_pois_path(repo_root: Path) -> Path:
    return repo_root / "data" / "events" / "landshift_pois.json"


def load_default_oceanscout_catalog(repo_root: Path) -> list[GeoEvent] | None:
    path = default_oceanscout_pois_path(repo_root)
    if not path.is_file():
        return None
    return load_events_file(path, profile="maritime", source="default_oceanscout_pois")


def load_default_landshift_catalog(repo_root: Path) -> list[GeoEvent] | None:
    path = default_landshift_pois_path(repo_root)
    if not path.is_file():
        return None
    return load_events_file(path, profile="land_use_change", source="default_landshift_pois")


def subsample_geo_events(
    events: list[GeoEvent],
    n: int,
    *,
    min_separation_km: float,
    seed: int,
) -> list[GeoEvent]:
    """
    Deterministic geographic spread: shuffle then greedily keep events at least
    min_separation_km apart (haversine), up to n items.
    """
    rng = random.Random(seed)
    pool = list(events)
    rng.shuffle(pool)
    picked: list[GeoEvent] = []
    for ev in pool:
        ok = True
        for p in picked:
            if haversine_km(ev.lon, ev.lat, p.lon, p.lat) < min_separation_km:
                ok = False
                break
        if ok:
            picked.append(ev)
        if len(picked) >= n:
            break
    return picked


def _sample_points(
    candidates: list[tuple[float, float]],
    n: int,
    *,
    min_separation_km: float,
    seed: int,
) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    pool = list(candidates)
    rng.shuffle(pool)
    picked: list[tuple[float, float]] = []
    for lat, lon in pool:
        ok = True
        for plat, plon in picked:
            if haversine_km(lon, lat, plon, plat) < min_separation_km:
                ok = False
                break
        if ok:
            picked.append((lat, lon))
        if len(picked) >= n:
            break
    return picked


def sample_coastal_locations(n: int, min_separation_km: float = 50, seed: int = 42) -> list[GeoEvent]:
    """
    Return synthetic coastal-ish samples for OceanScout.

    These are seeded from known maritime hubs; refine with external data later.
    """
    seeds = [
        (1.30, 103.85),  # Singapore
        (35.68, 139.76),  # Tokyo Bay
        (31.23, 121.47),  # Shanghai
        (25.77, -80.19),  # Miami
        (51.95, 4.14),  # Rotterdam
        (22.30, 114.17),  # Hong Kong
        (6.45, 3.39),  # Lagos
        (-34.60, -58.37),  # Buenos Aires
        (-33.86, 151.21),  # Sydney
        (24.86, 67.01),  # Karachi
        (37.77, -122.39),  # SF Bay
        (29.95, 32.55),  # Suez approach
    ]
    picked = _sample_points(seeds, n, min_separation_km=min_separation_km, seed=seed)
    out: list[GeoEvent] = []
    for i, (lat, lon) in enumerate(picked):
        out.append(
            GeoEvent(
                event_id=f"coastal_{i:05d}",
                lat=lat,
                lon=lon,
                event_date="2025-06-01",
                profile="maritime",
                source="seeded_ports",
                metadata={},
            )
        )
    return out


def sample_land_change_locations(n: int, seed: int = 42) -> list[GeoEvent]:
    seeds = [
        (-3.12, -60.02),  # Amazon fringe
        (-15.79, -47.88),  # Cerrado
        (0.35, 32.58),  # East Africa
        (13.75, 100.50),  # SE Asia peri-urban
        (30.04, 31.23),  # Nile corridor
        (22.57, 88.36),  # delta/agri region
        (40.71, -74.00),  # urban expansion edges
        (34.05, -118.24),  # dryland peri-urban
        (48.85, 2.35),  # temperate mixed-use
        (-26.20, 28.04),  # South Africa mixed
    ]
    picked = _sample_points(seeds, n, min_separation_km=150, seed=seed)
    out: list[GeoEvent] = []
    for i, (lat, lon) in enumerate(picked):
        out.append(
            GeoEvent(
                event_id=f"landshift_{i:05d}",
                lat=lat,
                lon=lon,
                event_date="2025-07-01",
                profile="land_use_change",
                source="seeded_land_change",
                metadata={},
            )
        )
    return out

