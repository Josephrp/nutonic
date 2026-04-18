#!/usr/bin/env python3
"""
Build per-location geographic context from Natural Earth vectors + catalog truth.

Normative: docs/scripts/SPEC-build-poi-geo-context.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml
from fetch_geo_baselines import ne_50m_artifacts
from shapely.geometry import Point

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_ROOT = REPO_ROOT / "data" / "catalog"
DEFAULT_GEO_ROOT = REPO_ROOT / "data" / "geo"
DEFAULT_CONTENT_VERSION = "dev"
SCHEMA_VERSION = "nutonic.geo_context.v1"
HINT_FACTS_SCHEMA = "nutonic.hint_compile_facts.v1"


def _hemisphere(lat: float) -> str:
    return "Northern" if lat >= 0.0 else "Southern"


def _latitude_band(lat: float) -> str:
    a = abs(lat)
    if a < 23.5:
        return "low_latitudes_tropical_subtropical"
    if a < 50.0:
        return "mid_latitudes_temperate"
    if a < 66.5:
        return "high_mid_latitudes_cool_temperate"
    return "polar_subpolar"


def _feature_proximity(d_km: float | None, has_name: bool) -> str:
    if not has_name or d_km is None:
        return "none"
    if d_km < 3.0:
        return "immediate"
    if d_km < 15.0:
        return "near"
    if d_km < 60.0:
        return "regional"
    return "distant"


def _coast_proximity(d_km: float | None) -> str:
    if d_km is None:
        return "unknown"
    if d_km < 25.0:
        return "sea_adjacent"
    if d_km < 100.0:
        return "near_coast"
    if d_km < 400.0:
        return "midcontinent"
    return "distant_maritime"


def _marine_framing(coast_km: float | None) -> str:
    """Ordinal, coordinate-free phrase for compile templates (no numeric km)."""
    if coast_km is None:
        return "Coastline distance bucket unavailable for this clip; treat marine proximity as unknown."
    if coast_km < 25.0:
        return "Maritime context: very close to a mapped coastline in the regional vector clip."
    if coast_km < 100.0:
        return "Maritime context: coastal hinterland within a short overland reach of the mapped shore."
    if coast_km < 400.0:
        return "Maritime context: clearly inland, but still within a few hundred kilometers of the mapped coast."
    return "Maritime context: deep interior relative to the mapped coastline in this clip."


def _hydro_framing(river_name: str | None, river_px: str, lake_name: str | None, lake_px: str) -> str:
    parts: list[str] = []
    if river_name and river_px != "none":
        parts.append(f"Named linear water ({river_name}) is {river_px.replace('_', ' ')} in the search footprint.")
    else:
        parts.append("No strong named linear-water signal in the search footprint.")
    if lake_name and lake_px != "none":
        parts.append(f"Standing water feature ({lake_name}) is {lake_px.replace('_', ' ')}.")
    else:
        parts.append("No standing-water highlight in the footprint.")
    return " ".join(parts)


def _hydro_framing_short(river_name: str | None, lake_name: str | None) -> str:
    if river_name and lake_name:
        return f"Linear water {river_name}; standing water {lake_name}."
    if river_name:
        return f"Linear water {river_name}."
    if lake_name:
        return f"Standing water {lake_name}."
    return "Hydrology labels thin in this footprint."


def _hint_compile_facts(
    *,
    continent: str | None,
    admin0_name: str | None,
    admin1_name: str | None,
    truth_lat: float,
    river_name: str | None,
    river_km: float | None,
    lake_name: str | None,
    lake_km: float | None,
    coast_km: float | None,
) -> dict[str, Any]:
    rpx = _feature_proximity(river_km, bool(river_name))
    lpx = _feature_proximity(lake_km, bool(lake_name))
    cpx = _coast_proximity(coast_km)
    return {
        "schema_version": HINT_FACTS_SCHEMA,
        "continent": continent or "Unknown continent",
        "hemisphere": _hemisphere(truth_lat),
        "latitude_band": _latitude_band(truth_lat),
        "admin0_name": admin0_name or "",
        "admin1_name": admin1_name or "",
        "nearest_river_label": river_name or "",
        "nearest_lake_label": lake_name or "",
        "river_proximity": rpx,
        "lake_proximity": lpx,
        "coast_proximity": cpx,
        "marine_framing": _marine_framing(coast_km),
        "hydro_framing": _hydro_framing(river_name, rpx, lake_name, lpx),
        "hydro_framing_short": _hydro_framing_short(river_name, lake_name),
    }


def _geo_root_from_env_or_default(cli_geo_root: Path | None) -> Path:
    if cli_geo_root is not None:
        return cli_geo_root
    env = os.environ.get("NE_FIXTURE_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return DEFAULT_GEO_ROOT


def resolve_vector_path(geo_root: Path, extract_name: str) -> Path | None:
    """NE unzip layout: natural_earth/50m/<extract>/<extract>.shp — or .geojson for CI fixtures."""
    base = geo_root / "natural_earth" / "50m" / extract_name
    for suffix in (".shp", ".geojson"):
        p = base / f"{extract_name}{suffix}"
        if p.is_file():
            return p
    return None


def _read_ne_version(geo_root: Path) -> str:
    manifest = geo_root / "MANIFEST.json"
    if not manifest.is_file():
        return "unknown"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "unknown"
    v = data.get("natural_earth_version")
    return str(v) if v else "unknown"


def pick_projected_crs(lon: float, lat: float) -> str:
    """Per-POI projected CRS: UTM where valid; Web Mercator near poles."""
    if abs(lat) > 84.0:
        return "EPSG:3857"
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    if lat >= 0.0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def _radius_meters(
    truth_lat: float,
    truth_lon: float,
    bbox_km_half: float | None,
    *,
    r_max_km: float,
    r_scale_k: float,
) -> float:
    if bbox_km_half is not None and bbox_km_half > 0:
        r_km = min(r_max_km, r_scale_k * float(bbox_km_half))
    else:
        r_km = r_max_km
    return max(1000.0, r_km * 1000.0)


def _row_get(row: Any, key: str) -> Any:
    """Field lookup safe for pandas Series (``Series.name`` is the index label, not a ``name`` column)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        index = row.index
    except AttributeError:
        return None
    if key in index:
        return row[key]
    return None


def _admin0_name(row: Any) -> str | None:
    if row is None:
        return None
    for key in ("ADMIN", "NAME", "name"):
        v = _row_get(row, key)
        if v is not None and str(v).strip() and str(v) != "-99":
            return str(v).strip()
    return None


def _continent(row: Any) -> str | None:
    if row is None:
        return None
    v = _row_get(row, "CONTINENT")
    if v is not None and str(v).strip() and str(v) not in ("-99", "Seven seas (open ocean)"):
        return str(v).strip()
    return None


def _admin1_name(row: Any) -> str | None:
    if row is None:
        return None
    for key in ("NAME_1", "name", "NAME"):
        v = _row_get(row, key)
        if v is not None and str(v).strip() and str(v) != "-99":
            return str(v).strip()
    return None


def _iso_a2(row: Any) -> str | None:
    if row is None:
        return None
    for key in ("ISO_A2", "WB_A2", "ADM0_A3"):
        v = _row_get(row, key)
        if v is not None:
            s = str(v).strip().upper()
            if s and s not in ("-99", ""):
                if len(s) == 2 and s.isalpha():
                    return s
    return None


def _line_name(row: Any) -> str | None:
    if row is None:
        return None
    for key in ("name", "NAME", "Name"):
        v = _row_get(row, key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _pick_admin0(
    admin0: gpd.GeoDataFrame,
    pt_metric: Point,
    metric_crs: str,
    country_iso: str | None,
) -> Any:
    """Row-like (Series) or None."""
    if admin0.empty:
        return None
    a0 = admin0.to_crs(metric_crs)
    mask = a0.contains(pt_metric) | a0.touches(pt_metric)
    hits = a0[mask]
    if not hits.empty:
        if len(hits) > 1:
            areas = hits.geometry.area
            hits = hits.loc[[areas.idxmin()]]
        return hits.iloc[0]

    if country_iso:
        iso = country_iso.strip().upper()
        cand = a0[a0.apply(lambda r: (_iso_a2(r) == iso), axis=1)]
        if not cand.empty:
            dists = cand.geometry.centroid.distance(pt_metric)
            return cand.loc[dists.idxmin()]

    return None


def _pick_admin1(
    admin1: gpd.GeoDataFrame,
    pt_metric: Point,
    metric_crs: str,
) -> Any:
    if admin1.empty:
        return None
    a1 = admin1.to_crs(metric_crs)
    mask = a1.contains(pt_metric) | a1.touches(pt_metric)
    hits = a1[mask]
    if hits.empty:
        return None
    if len(hits) > 1:
        areas = hits.geometry.area
        hits = hits.loc[[areas.idxmin()]]
    return hits.iloc[0]


def _nearest_linear_feature(
    lines: gpd.GeoDataFrame,
    pt_metric: Point,
    metric_crs: str,
    search_geom_metric,
) -> tuple[str | None, float | None]:
    if lines.empty:
        return None, None
    g = lines.to_crs(metric_crs)
    nearby = g[g.intersects(search_geom_metric)]
    if nearby.empty:
        nearby = g
    try:
        dists = nearby.geometry.distance(pt_metric)
    except Exception:
        return None, None
    idx = dists.idxmin()
    row = nearby.loc[idx]
    d_m = float(dists.loc[idx])
    return _line_name(row), d_m / 1000.0


def _coast_distance_km(
    coast: gpd.GeoDataFrame,
    pt_metric: Point,
    metric_crs: str,
) -> float | None:
    if coast.empty:
        return None
    c = coast.to_crs(metric_crs)
    try:
        d_m = float(c.geometry.distance(pt_metric).min())
    except Exception:
        return None
    return d_m / 1000.0


def build_context_for_location(
    location_id: str,
    truth_lat: float,
    truth_lon: float,
    *,
    bbox_km_half: float | None,
    country_iso: str | None,
    admin0: gpd.GeoDataFrame,
    admin1: gpd.GeoDataFrame,
    rivers: gpd.GeoDataFrame,
    lakes: gpd.GeoDataFrame,
    coast: gpd.GeoDataFrame,
    ne_version: str,
    r_max_km: float,
    r_scale_k: float,
) -> dict[str, Any]:
    metric_crs = pick_projected_crs(truth_lon, truth_lat)
    pt = Point(truth_lon, truth_lat)
    pt_metric = gpd.GeoDataFrame(geometry=[pt], crs="EPSG:4326").to_crs(metric_crs).geometry.iloc[0]
    r_m = _radius_meters(truth_lat, truth_lon, bbox_km_half, r_max_km=r_max_km, r_scale_k=r_scale_k)
    buf = pt_metric.buffer(r_m)

    admin0_row = _pick_admin0(admin0, pt_metric, metric_crs, country_iso)
    admin1_row = _pick_admin1(admin1, pt_metric, metric_crs)

    river_name, river_km = _nearest_linear_feature(rivers, pt_metric, metric_crs, buf)
    lake_name, lake_km = _nearest_linear_feature(lakes, pt_metric, metric_crs, buf)
    coast_km = _coast_distance_km(coast, pt_metric, metric_crs)

    adm0 = _admin0_name(admin0_row)
    adm1 = _admin1_name(admin1_row)
    cont = _continent(admin0_row)

    return {
        "location_id": location_id,
        "schema_version": SCHEMA_VERSION,
        "truth": {"lat": float(truth_lat), "lon": float(truth_lon)},
        "admin0_name": adm0,
        "admin1_name": adm1,
        "continent": cont,
        "nearest_river": {"name": river_name, "distance_km": river_km},
        "nearest_lake": {"name": lake_name, "distance_km": lake_km},
        "coast_distance_km": coast_km,
        "feature_distances": [],
        "hint_compile_facts": _hint_compile_facts(
            continent=cont,
            admin0_name=adm0,
            admin1_name=adm1,
            truth_lat=truth_lat,
            river_name=river_name,
            river_km=river_km,
            lake_name=lake_name,
            lake_km=lake_km,
            coast_km=coast_km,
        ),
        "sources": {
            "natural_earth_version": ne_version,
            "layers": ["admin_0", "admin_1", "rivers", "lakes", "coastline"],
            "projected_crs": metric_crs,
            "search_radius_m": round(r_m, 3),
        },
    }


def _load_location_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping")
    return data


def _iter_location_files(catalog_root: Path) -> list[Path]:
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return []
    return sorted(p for p in loc_dir.glob("*.yaml") if p.is_file())


def load_layers(geo_root: Path) -> dict[str, gpd.GeoDataFrame]:
    out: dict[str, gpd.GeoDataFrame] = {}
    layer_keys = ("admin_0", "admin_1", "rivers", "lakes", "coastline")
    attr_map = list(zip(layer_keys, ne_50m_artifacts(), strict=True))
    for key, art in attr_map:
        p = resolve_vector_path(geo_root, art.extract_name)
        if p is None:
            raise FileNotFoundError(f"Missing vector layer for {key}: expected under {geo_root}/natural_earth/50m/{art.extract_name}/")
        out[key] = gpd.read_file(p)
    return out


def _truth_finite_in_range(lat: float, lon: float) -> bool:
    if not math.isfinite(lat) or not math.isfinite(lon):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return True


def _bbox_km_half_sane(bh: float | None) -> bool:
    if bh is None:
        return True
    if not math.isfinite(float(bh)) or float(bh) <= 0.0:
        return False
    return True


def run_build(
    catalog_root: Path,
    geo_root: Path,
    output_dir: Path,
    *,
    r_max_km: float,
    r_scale_k: float,
    allow_partial: bool = False,
) -> int:
    try:
        layers = load_layers(geo_root)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        print("Run: python data/scripts/fetch_geo_baselines.py", file=sys.stderr)
        return 6
    except Exception as e:
        print(f"Failed to load geo layers: {e}", file=sys.stderr)
        return 7

    ne_ver = _read_ne_version(geo_root)
    loc_files = _iter_location_files(catalog_root)
    if not loc_files:
        print(f"No YAML locations under {catalog_root / 'locations'}", file=sys.stderr)
        return 6

    admin0 = layers["admin_0"]
    admin1 = layers["admin_1"]
    rivers = layers["rivers"]
    lakes = layers["lakes"]
    coast = layers["coastline"]

    output_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for ypath in loc_files:
        try:
            row = _load_location_yaml(ypath)
        except Exception as e:
            print(f"{ypath}: {e}", file=sys.stderr)
            if allow_partial:
                skipped += 1
                continue
            return 7

        lid = str(row.get("location_id") or ypath.stem)
        try:
            lat = float(row["truth_lat"])
            lon = float(row["truth_lon"])
        except (KeyError, TypeError, ValueError) as e:
            print(f"{ypath}: invalid truth_lat/truth_lon: {e}", file=sys.stderr)
            if allow_partial:
                skipped += 1
                continue
            return 7

        if not _truth_finite_in_range(lat, lon):
            print(f"{ypath}: truth coordinates out of range or non-finite (lat={lat!r}, lon={lon!r})", file=sys.stderr)
            if allow_partial:
                skipped += 1
                continue
            return 7

        bbox_half = row.get("bbox_km_half")
        bh = float(bbox_half) if bbox_half is not None else None
        if not _bbox_km_half_sane(bh):
            print(f"{ypath}: invalid bbox_km_half {bbox_half!r}", file=sys.stderr)
            if allow_partial:
                skipped += 1
                continue
            return 7
        ciso = row.get("country_iso")
        ciso_s = str(ciso) if ciso else None

        try:
            ctx = build_context_for_location(
                lid,
                lat,
                lon,
                bbox_km_half=bh,
                country_iso=ciso_s,
                admin0=admin0,
                admin1=admin1,
                rivers=rivers,
                lakes=lakes,
                coast=coast,
                ne_version=ne_ver,
                r_max_km=r_max_km,
                r_scale_k=r_scale_k,
            )
        except Exception as e:
            print(f"{ypath}: geometry error: {e}", file=sys.stderr)
            if allow_partial:
                skipped += 1
                continue
            return 7

        out_path = output_dir / f"{lid}.json"
        out_path.write_text(json.dumps(ctx, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(out_path.as_posix())
        written += 1

    if written == 0:
        print(
            "build_poi_geo_context: no geo_context files written "
            f"(locations={len(loc_files)}, skipped={skipped}, allow_partial={allow_partial})",
            file=sys.stderr,
        )
        return 9
    if skipped:
        print(
            f"build_poi_geo_context: wrote {written} geo_context file(s), skipped {skipped} location(s)",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build geo_context/*.json from catalog + Natural Earth.")
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    parser.add_argument("--geo-root", type=Path, default=None, help="Default: data/geo or NE_FIXTURE_ROOT env.")
    parser.add_argument(
        "--content-version",
        default=os.environ.get("NUTONIC_CONTENT_VERSION", DEFAULT_CONTENT_VERSION),
        help="Cache segment (default dev or NUTONIC_CONTENT_VERSION).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="geo_context directory; default data/cache/<content-version>/geo_context",
    )
    parser.add_argument("--r-max-km", type=float, default=200.0)
    parser.add_argument("--r-scale-k", type=float, default=3.0)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Skip locations with bad coordinates or Natural Earth geometry failures; exit 0 if at least one file is written.",
    )
    args = parser.parse_args(argv)

    geo_root = _geo_root_from_env_or_default(args.geo_root)
    allow_partial = bool(args.allow_partial) or os.environ.get(
        "NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL", ""
    ).strip().lower() in ("1", "true", "yes")
    if args.output_dir is not None:
        out_dir = args.output_dir
    else:
        out_dir = REPO_ROOT / "data" / "cache" / str(args.content_version) / "geo_context"

    return run_build(
        args.catalog_root.resolve(),
        geo_root.resolve(),
        out_dir.resolve(),
        r_max_km=args.r_max_km,
        r_scale_k=args.r_scale_k,
        allow_partial=allow_partial,
    )


if __name__ == "__main__":
    raise SystemExit(main())
