#!/usr/bin/env python3
"""
Import GeoGuessr-style POI trees into data/catalog/ (YAML maps index + per-location files).

Normative: docs/scripts/SPEC-catalog-import-poi.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POI_ROOT = REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12"
DEFAULT_CATALOG_ROOT = REPO_ROOT / "data" / "catalog"


class CatalogImportError(Exception):
    """Validation error → exit code 2."""

    pass


def _safe_relative_to_repo(path: Path, repo_root: Path) -> Path:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(repo_root.resolve())
    except ValueError as e:
        raise CatalogImportError(f"Path escapes repository root: {path}") from e
    if ".." in rel.parts:
        raise CatalogImportError(f"Invalid relative path (..): {rel}")
    return rel


def normalize_mapbox_path(raw: str | None, repo_root: Path) -> str | None:
    """Return repo-root-relative POSIX path, or None if raw is empty."""
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        candidate = (repo_root / p).resolve()
    else:
        candidate = p.resolve()
    rel = _safe_relative_to_repo(candidate, repo_root)
    return rel.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_poi_jobs_layout_a(poi_root: Path) -> list[dict[str, Any]]:
    manifest = poi_root / "geoguessr_poi_manifest.json"
    if not manifest.is_file():
        return []
    data = _load_json(manifest)
    points = data.get("points")
    if not isinstance(points, list):
        raise CatalogImportError(f"{manifest}: missing or invalid 'points' list")
    return points


def _discover_poi_jobs_layout_b(poi_root: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for poi_json in sorted(poi_root.glob("poi_*/poi.json")):
        jobs.append(_load_json(poi_json))
    return jobs


def _merge_point_with_poi_json(point: dict[str, Any], poi_root: Path) -> dict[str, Any]:
    poi_id = point.get("poi_id")
    if not poi_id:
        raise CatalogImportError("Manifest point missing poi_id")
    detail = poi_root / str(poi_id) / "poi.json"
    if detail.is_file():
        merged = dict(point)
        merged.update(_load_json(detail))
        return merged
    return dict(point)


def _pick_truth_coords(row: dict[str, Any]) -> tuple[float, float]:
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
    except (KeyError, TypeError, ValueError) as e:
        raise CatalogImportError(f"Missing or invalid latitude/longitude for {row.get('poi_id')!r}") from e
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise CatalogImportError(f"Out-of-range coordinates for {row.get('poi_id')!r}: lat={lat} lon={lon}")
    return lat, lon


def _still_source_for_row(row: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    mapbox = row.get("mapbox") or {}
    raw_path = mapbox.get("path")
    skipped = bool(mapbox.get("skipped"))
    rel = normalize_mapbox_path(raw_path, repo_root) if raw_path else None
    if rel and not skipped:
        candidate = repo_root / rel
        if candidate.is_file():
            return {"bundled_relative": rel}
    lat, lon = _pick_truth_coords(row)
    return {
        "render_policy": {
            "center_lat": lat,
            "center_lon": lon,
            "zoom": 12.0,
            "width_px": 1280,
            "height_px": 1280,
            "style": "satellite-v9",
        }
    }


def _location_yaml_dict(row: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    poi_id = row.get("poi_id")
    if not poi_id:
        raise CatalogImportError("Row missing poi_id")
    lat, lon = _pick_truth_coords(row)
    hf = row.get("hf_row_meta") or {}
    country = hf.get("country_iso_alpha2")
    out: dict[str, Any] = {
        "location_id": str(poi_id),
        "map_id": str(poi_id),
        "truth_lat": lat,
        "truth_lon": lon,
        "assist_level": "standard",
        "still_source": _still_source_for_row(row, repo_root),
    }
    if country:
        out["country_iso"] = str(country)
    bbox = row.get("bbox_wgs84")
    if isinstance(bbox, list) and len(bbox) == 4:
        out["bbox_wgs84"] = [float(x) for x in bbox]
    if "bbox_km_half" in row and row["bbox_km_half"] is not None:
        out["bbox_km_half"] = float(row["bbox_km_half"])
    return out


def _apply_ranked_split_half(map_rows: list[dict[str, Any]]) -> None:
    """Stable ~50/50 split for ``maps.yaml`` ``ranked_pool`` (first ``n//2`` ids false, rest true).

    Lexical sort on ``map_id`` keeps runs reproducible across machines. Odd ``n`` yields one extra
    ``ranked_pool: true`` row (for example 11 maps → 5 non-ranked pool + 6 ranked pool).
    """
    if not map_rows:
        return
    rows = sorted(map_rows, key=lambda m: str(m.get("map_id", "")))
    n = len(rows)
    cut = n // 2
    for i, m in enumerate(rows):
        m["ranked_pool"] = i >= cut


def _default_map_row(location_id: str, row: dict[str, Any]) -> dict[str, Any]:
    hf = row.get("hf_row_meta") or {}
    addr = hf.get("address")
    title = str(addr).strip() if addr else f"POI {location_id}"
    if len(title) > 120:
        title = title[:117] + "..."
    return {
        "map_id": location_id,
        "title": title,
        "local_only": True,
        "ranked_pool": False,
    }


def _load_map_overrides(maps_file: Path | None) -> dict[str, dict[str, Any]]:
    if maps_file is None or not maps_file.is_file():
        return {}
    raw = yaml.safe_load(maps_file.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CatalogImportError(f"{maps_file}: expected YAML mapping at root")
    ov = raw.get("overrides") or raw.get("map_overrides")
    if not isinstance(ov, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in ov.items():
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


def _deep_merge_map(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for k, v in extra.items():
        merged[k] = v
    return merged


def _load_existing_maps_index(catalog_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    maps_yaml = catalog_root / "maps.yaml"
    if not maps_yaml.is_file():
        return [], None
    data = yaml.safe_load(maps_yaml.read_text(encoding="utf-8")) or {}
    maps = data.get("maps")
    if maps is None:
        maps = []
    if not isinstance(maps, list):
        raise CatalogImportError(f"{maps_yaml}: 'maps' must be a list")
    cv = data.get("content_version")
    cv_s = str(cv) if cv is not None else None
    return [m for m in maps if isinstance(m, dict)], cv_s


def _write_maps_yaml(catalog_root: Path, maps: list[dict[str, Any]], content_version: str | None) -> None:
    maps_sorted = sorted(maps, key=lambda m: str(m.get("map_id", "")))
    root: dict[str, Any] = {"maps": maps_sorted}
    if content_version:
        root["content_version"] = content_version
    text = yaml.safe_dump(root, sort_keys=False, allow_unicode=True, default_flow_style=False)
    (catalog_root / "maps.yaml").write_text(text, encoding="utf-8", newline="\n")


def collect_import_jobs(poi_root: Path) -> list[dict[str, Any]]:
    layout_a = _discover_poi_jobs_layout_a(poi_root)
    if layout_a:
        return [_merge_point_with_poi_json(p, poi_root) for p in layout_a]
    layout_b = _discover_poi_jobs_layout_b(poi_root)
    if not layout_b:
        raise CatalogImportError(f"No POI sources under {poi_root} (need manifest or poi_*/poi.json)")
    return layout_b


def plan_import(
    poi_root: Path,
    repo_root: Path,
    catalog_root: Path,
    *,
    force: bool,
    map_overrides: dict[str, dict[str, Any]],
    ranked_split: str | None = None,
    poi_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Returns (location_dicts, merged_maps_for_maps_yaml, warnings)."""
    jobs = collect_import_jobs(poi_root)
    if poi_limit is not None:
        if poi_limit < 0:
            raise CatalogImportError("--poi-limit must be >= 0")
        jobs = jobs[:poi_limit]
    seen_ids: set[str] = set()
    locations: list[dict[str, Any]] = []
    map_rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for row in jobs:
        loc = _location_yaml_dict(row, repo_root)
        lid = loc["location_id"]
        if lid in seen_ids:
            raise CatalogImportError(f"Duplicate location_id in source data: {lid}")
        seen_ids.add(lid)
        loc_path = catalog_root / "locations" / f"{lid}.yaml"
        if loc_path.exists() and not force:
            raise CatalogImportError(f"Refusing to overwrite existing {loc_path} (use --force)")
        if isinstance(loc["still_source"], dict) and "bundled_relative" in loc["still_source"]:
            rel = loc["still_source"]["bundled_relative"]
            if not (repo_root / rel).is_file():
                warnings.append(f"{lid}: bundled still missing at {rel}; wrote render_policy fallback")
                lat, lon = loc["truth_lat"], loc["truth_lon"]
                loc["still_source"] = {
                    "render_policy": {
                        "center_lat": lat,
                        "center_lon": lon,
                        "zoom": 12.0,
                        "width_px": 1280,
                        "height_px": 1280,
                        "style": "satellite-v9",
                    }
                }
        mrow = _default_map_row(lid, row)
        if lid in map_overrides:
            mrow = _deep_merge_map(mrow, map_overrides[lid])
        locations.append(loc)
        map_rows.append(mrow)

    if ranked_split == "half":
        _apply_ranked_split_half(map_rows)

    existing_maps, cv = _load_existing_maps_index(catalog_root)
    by_id = {str(m.get("map_id")): dict(m) for m in existing_maps if m.get("map_id")}
    for m in map_rows:
        mid = str(m["map_id"])
        by_id[mid] = m
    merged_list = list(by_id.values())
    return locations, merged_list, warnings


def run_import(
    poi_root: Path,
    repo_root: Path,
    catalog_root: Path,
    *,
    dry_run: bool,
    force: bool,
    maps_file: Path | None,
    content_version: str | None,
    ranked_split: str | None = None,
    poi_limit: int | None = None,
) -> int:
    poi_root = poi_root.resolve()
    catalog_root = catalog_root.resolve()
    overrides = _load_map_overrides(maps_file)
    try:
        locations, merged_maps, warnings = plan_import(
            poi_root,
            repo_root,
            catalog_root,
            force=force,
            map_overrides=overrides,
            ranked_split=ranked_split,
            poi_limit=poi_limit,
        )
    except CatalogImportError as e:
        print(f"catalog_import_poi: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"catalog_import_poi: I/O error: {e}", file=sys.stderr)
        return 3

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    _, existing_cv = _load_existing_maps_index(catalog_root)
    cv_out = content_version or existing_cv or "0"

    if dry_run:
        print(f"Planned {len(locations)} location(s) under {catalog_root / 'locations'}")
        for loc in locations:
            print(f"  - {loc['location_id']}.yaml")
        print(f"maps.yaml would contain {len(merged_maps)} map row(s); content_version={cv_out!r}")
        return 0

    try:
        (catalog_root / "locations").mkdir(parents=True, exist_ok=True)
        for loc in locations:
            lid = loc["location_id"]
            path = catalog_root / "locations" / f"{lid}.yaml"
            path.write_text(
                yaml.safe_dump(loc, sort_keys=False, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
                newline="\n",
            )
        _write_maps_yaml(catalog_root, merged_maps, cv_out)
    except OSError as e:
        print(f"catalog_import_poi: I/O error: {e}", file=sys.stderr)
        return 3

    print(f"Wrote {len(locations)} location file(s) and maps.yaml under {catalog_root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import POI downloads into data/catalog/")
    p.add_argument("--poi-root", type=Path, default=DEFAULT_POI_ROOT, help="Root containing manifest or poi_*/poi.json")
    p.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT, help="Catalog output directory")
    p.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root for path normalization")
    p.add_argument("--dry-run", action="store_true", help="Validate and print planned writes only")
    p.add_argument("--force", action="store_true", help="Overwrite existing location YAML files")
    p.add_argument("--maps-file", type=Path, default=None, help="YAML with map_overrides / overrides by map_id")
    p.add_argument("--content-version", type=str, default=None, help="Write content_version into maps.yaml")
    p.add_argument(
        "--ranked-split",
        choices=("none", "half"),
        default="none",
        help="half: after import, set ranked_pool false for first n//2 map_ids (sorted), true for the rest",
    )
    p.add_argument(
        "--poi-limit",
        type=int,
        default=None,
        metavar="N",
        help="Import at most the first N POIs from manifest order (layout A) or sorted poi_*/ order (layout B)",
    )
    args = p.parse_args(argv)
    rs = None if args.ranked_split == "none" else args.ranked_split
    return run_import(
        args.poi_root,
        args.repo_root,
        args.catalog_root,
        dry_run=args.dry_run,
        force=args.force,
        maps_file=args.maps_file,
        content_version=args.content_version,
        ranked_split=rs,
        poi_limit=args.poi_limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
