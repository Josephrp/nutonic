#!/usr/bin/env python3
"""
Emit AiGuessRow fixtures (map_id, location_id, ai_lat, ai_lon) for manifest ai_guesses[].

Normative: docs/scripts/SPEC-generate-ai-guess-fixture.md
TiM / TerraTorch contract (Coordinates → ai_lat/ai_lon): docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_CSV = 10
EXIT_TIM_SCHEMA = 12
EXIT_CONFLICT = 13


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected YAML mapping at root")
    return raw


def iter_catalog_locations(catalog_root: Path) -> list[dict[str, Any]]:
    """Rows: map_id, location_id, truth_lat, truth_lon (sorted by location_id)."""
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for ypath in sorted(loc_dir.glob("*.yaml")):
        loc = _load_yaml_mapping(ypath)
        lid = str(loc.get("location_id") or ypath.stem)
        mid = str(loc.get("map_id") or lid)
        rows.append(
            {
                "location_id": lid,
                "map_id": mid,
                "truth_lat": float(loc["truth_lat"]),
                "truth_lon": float(loc["truth_lon"]),
            }
        )
    rows.sort(key=lambda r: r["location_id"])
    return rows


def _coord_pair_from_mapping(c: Mapping[str, Any]) -> tuple[float, float] | None:
    """Return (lat, lon) from a coordinates sub-object."""
    lat = c.get("latitude", c.get("lat"))
    lon = c.get("longitude", c.get("lon"))
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def extract_tim_coordinates(record: Mapping[str, Any]) -> tuple[float, float] | None:
    """
    Parse TiM / bundle export: top-level ai_lat/ai_lon or tim_modality_outputs.Coordinates.

    Supports PRO-style discriminated objects::
        { "kind": "coordinates_wgs84", "latitude": …, "longitude": … }
    and shorthand { "lat", "lon" } inside ``Coordinates``.
    """
    alat = record.get("ai_lat")
    alon = record.get("ai_lon")
    if alat is not None and alon is not None:
        return float(alat), float(alon)

    tmo = record.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return None

    coords = tmo.get("Coordinates")
    if coords is None:
        coords = tmo.get("coordinates")

    if isinstance(coords, dict):
        kind = str(coords.get("kind", "")).lower()
        if kind in ("coordinates_wgs84", "coordinates", ""):
            pair = _coord_pair_from_mapping(coords)
            if pair is not None:
                return pair
        return None

    if isinstance(coords, list):
        for item in coords:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).lower()
            if kind in ("coordinates_wgs84", "coordinates"):
                pair = _coord_pair_from_mapping(item)
                if pair is not None:
                    return pair
        return None

    return None


def _row_key(map_id: str, location_id: str) -> tuple[str, str]:
    return (map_id, location_id)


def load_tim_jsonl(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """Map (map_id, location_id) -> (ai_lat, ai_lon). Every line must include ``map_id`` (stable catalog join)."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{line_no}: expected object")
        lid = obj.get("location_id")
        if lid is None:
            raise ValueError(f"{path}:{line_no}: missing location_id")
        lid_s = str(lid)
        mid_raw = obj.get("map_id")
        if mid_raw is None:
            raise ValueError(f"{path}:{line_no}: missing map_id (required for JSONL join)")
        pair = extract_tim_coordinates(obj)
        if pair is None:
            raise ValueError(f"{path}:{line_no}: missing TiM coordinates for location_id={lid_s}")
        alat, alon = pair
        k = _row_key(str(mid_raw), lid_s)
        if k in out:
            raise ValueError(f"{path}: duplicate (map_id, location_id)={k}")
        out[k] = (alat, alon)
    return out


def load_tim_dir(tim_dir: Path) -> dict[tuple[str, str], tuple[float, float]]:
    out: dict[tuple[str, str], tuple[float, float]] = {}
    paths = sorted(tim_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"No *.json under {tim_dir}")
    for p in paths:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError(f"{p}: root must be object")
        lid = obj.get("location_id")
        if lid is None:
            raise ValueError(f"{p}: missing location_id")
        mid = obj.get("map_id")
        if mid is None:
            raise ValueError(f"{p}: missing map_id (required for tim_dir rows)")
        pair = extract_tim_coordinates(obj)
        if pair is None:
            raise ValueError(f"{p}: missing tim_modality_outputs coordinates")
        k = _row_key(str(mid), str(lid))
        if k in out:
            raise ValueError(f"Duplicate tim_dir key {k} ({p})")
        out[k] = pair
    return out


def _ai_row(map_id: str, location_id: str, ai_lat: float, ai_lon: float) -> dict[str, Any]:
    return {
        "ai_lat": ai_lat,
        "ai_lon": ai_lon,
        "location_id": location_id,
        "map_id": map_id,
    }


def mode_decoy_offset(
    locations: list[dict[str, Any]],
    *,
    delta_km: float,
    bearing_deg: float,
) -> dict[tuple[str, str], tuple[float, float]]:
    from geo_nutonic import destination_point_km

    out: dict[tuple[str, str], tuple[float, float]] = {}
    for loc in locations:
        lon_t = float(loc["truth_lon"])
        lat_t = float(loc["truth_lat"])
        lon_ai, lat_ai = destination_point_km(lon_t, lat_t, bearing_deg, delta_km)
        out[_row_key(loc["map_id"], loc["location_id"])] = (lat_ai, lon_ai)
    return out


def mode_fixed_table(
    locations: list[dict[str, Any]],
    csv_path: Path,
) -> dict[tuple[str, str], tuple[float, float]]:
    by_lid: dict[str, dict[str, Any]] = {}
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")
        fields = {h.strip().lower(): h for h in reader.fieldnames}
        for req in ("location_id", "ai_lat", "ai_lon"):
            if req not in fields:
                raise ValueError(f"CSV missing column {req!r} (got {list(reader.fieldnames)})")
        for row in reader:
            lid = str(row[fields["location_id"]]).strip()
            if not lid:
                continue
            by_lid[lid] = row

    out: dict[tuple[str, str], tuple[float, float]] = {}
    for loc in locations:
        lid = loc["location_id"]
        if lid not in by_lid:
            raise ValueError(f"CSV missing row for location_id={lid}")
        r = by_lid[lid]
        lat = float(r[fields["ai_lat"]])
        lon = float(r[fields["ai_lon"]])
        mid = str(r.get(fields.get("map_id", ""), "") or "").strip() if "map_id" in fields else ""
        if mid and mid != loc["map_id"]:
            raise ValueError(f"CSV map_id mismatch for {lid}: csv={mid!r} catalog={loc['map_id']!r}")
        out[_row_key(loc["map_id"], lid)] = (lat, lon)
    return out


def mode_random_seeded(
    locations: list[dict[str, Any]],
    *,
    seed: int,
    min_km: float,
    max_km: float,
    min_sep_km: float,
    max_attempts: int = 200,
) -> dict[tuple[str, str], tuple[float, float]]:
    from geo_nutonic import destination_point_km, haversine_km

    rng = random.Random(seed)
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for loc in locations:
        lon_t = float(loc["truth_lon"])
        lat_t = float(loc["truth_lat"])
        placed = False
        for _ in range(max_attempts):
            bearing = rng.uniform(0.0, 360.0)
            dist = rng.uniform(min_km, max_km)
            lon_ai, lat_ai = destination_point_km(lon_t, lat_t, bearing, dist)
            sep = haversine_km(lon_t, lat_t, lon_ai, lat_ai)
            if sep >= min_sep_km - 1e-6:
                out[_row_key(loc["map_id"], loc["location_id"])] = (lat_ai, lon_ai)
                placed = True
                break
        if not placed:
            raise ValueError(
                f"random_seeded: could not place guess for {loc['location_id']} "
                f"with min_sep_km={min_sep_km} after {max_attempts} attempts"
            )
    return out


def mode_tim_only(
    locations: list[dict[str, Any]],
    tim_map: dict[tuple[str, str], tuple[float, float]],
) -> dict[tuple[str, str], tuple[float, float]]:
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for loc in locations:
        k = _row_key(loc["map_id"], loc["location_id"])
        if k not in tim_map:
            raise ValueError(f"TiM export missing row for map_id={loc['map_id']!r} location_id={loc['location_id']!r}")
        out[k] = tim_map[k]
    return out


def _haversine_pair(loc: Mapping[str, Any], ai_lat: float, ai_lon: float) -> float:
    from geo_nutonic import haversine_km

    return haversine_km(float(loc["truth_lon"]), float(loc["truth_lat"]), ai_lon, ai_lat)


def _merge_tim_over_base(
    locations: list[dict[str, Any]],
    base: dict[tuple[str, str], tuple[float, float]],
    tim_map: dict[tuple[str, str], tuple[float, float]],
    *,
    prefer_tim: bool,
    match_tol_km: float,
) -> dict[tuple[str, str], tuple[float, float]]:
    """TiM overlay vs decoy/fixed/random base. Exit semantics handled by caller via exceptions."""
    out = dict(base)
    for loc in locations:
        k = _row_key(loc["map_id"], loc["location_id"])
        if k not in tim_map:
            continue
        tlat, tlon = tim_map[k]
        if k not in base:
            out[k] = (tlat, tlon)
            continue
        blat, blon = base[k]
        from geo_nutonic import haversine_km

        d = haversine_km(blon, blat, tlon, tlat)
        if prefer_tim:
            out[k] = (tlat, tlon)
        else:
            if d > match_tol_km:
                raise ValueError(
                    f"Conflicting AI coordinates for {k}: base vs TiM differ by {d:.3f} km "
                    f"(> {match_tol_km} km) with --prefer-tim=false"
                )
            out[k] = (blat, blon)
    return out


def validate_rows(
    locations: list[dict[str, Any]],
    resolved: dict[tuple[str, str], tuple[float, float]],
    *,
    min_ai_vs_truth_km: float,
    max_ai_vs_truth_km: float | None,
) -> None:
    for loc in locations:
        k = _row_key(loc["map_id"], loc["location_id"])
        if k not in resolved:
            raise ValueError(f"Internal error: missing resolved row for {k}")
        alat, alon = resolved[k]
        if not (-90.0 <= alat <= 90.0 and -180.0 <= alon <= 180.0):
            raise ValueError(f"Out-of-range ai_lat/ai_lon for {k}: {alat}, {alon}")
        sep = _haversine_pair(loc, alat, alon)
        if min_ai_vs_truth_km > 0 and sep + 1e-6 < min_ai_vs_truth_km:
            raise ValueError(
                f"ai guess too close to truth for {k}: {sep:.3f} km < min {min_ai_vs_truth_km} km"
            )
        if max_ai_vs_truth_km is not None and sep > max_ai_vs_truth_km + 1e-6:
            raise ValueError(
                f"ai guess too far from truth for {k}: {sep:.3f} km > max {max_ai_vs_truth_km} km"
            )


def generate(
    *,
    catalog_root: Path,
    mode: str,
    output_path: Path,
    tim_export: Path | None,
    tim_dir: Path | None,
    prefer_tim: bool,
    tim_match_tol_km: float,
    delta_km: float | None,
    bearing_deg: float | None,
    csv_path: Path | None,
    seed: int | None,
    min_km: float | None,
    max_km: float | None,
    min_sep_km: float,
    min_ai_vs_truth_km: float,
    max_ai_vs_truth_km: float | None,
) -> list[dict[str, Any]]:
    locations = iter_catalog_locations(catalog_root)
    if not locations:
        raise ValueError(f"No catalog locations under {catalog_root / 'locations'}")

    tim_overlay: dict[tuple[str, str], tuple[float, float]] = {}
    base: dict[tuple[str, str], tuple[float, float]] = {}

    if mode == "terramind_tim_jsonl":
        if tim_export is None:
            raise ValueError("terramind_tim_jsonl requires --tim-export")
        if tim_dir is not None:
            raise ValueError("terramind_tim_jsonl: do not pass --tim-dir (use terramind_tim_dir mode instead)")
        base = mode_tim_only(locations, load_tim_jsonl(tim_export))
    elif mode == "terramind_tim_dir":
        if tim_dir is None:
            raise ValueError("terramind_tim_dir requires --tim-dir")
        if tim_export is not None:
            raise ValueError("terramind_tim_dir: do not pass --tim-export (use terramind_tim_jsonl mode instead)")
        base = mode_tim_only(locations, load_tim_dir(tim_dir))
    else:
        if tim_export is not None:
            tim_overlay.update(load_tim_jsonl(tim_export))
        if tim_dir is not None:
            dmap = load_tim_dir(tim_dir)
            overlap = set(tim_overlay) & set(dmap)
            if overlap:
                raise ValueError(f"--tim-export and --tim-dir both define keys (example {next(iter(overlap))})")
            tim_overlay.update(dmap)

        if mode == "decoy_offset":
            if delta_km is None or bearing_deg is None:
                raise ValueError("decoy_offset requires --delta-km and --bearing-deg")
            base = mode_decoy_offset(locations, delta_km=delta_km, bearing_deg=bearing_deg)
        elif mode == "fixed_table":
            if csv_path is None:
                raise ValueError("fixed_table requires --csv")
            base = mode_fixed_table(locations, csv_path)
        elif mode == "random_seeded":
            if seed is None or min_km is None or max_km is None:
                raise ValueError("random_seeded requires --seed, --min-km, --max-km")
            if min_km > max_km:
                raise ValueError("min-km must be <= max-km")
            base = mode_random_seeded(
                locations,
                seed=seed,
                min_km=min_km,
                max_km=max_km,
                min_sep_km=min_sep_km,
            )
        else:
            raise ValueError(f"Unknown mode {mode!r}")

        if tim_overlay:
            base = _merge_tim_over_base(
                locations,
                base,
                tim_overlay,
                prefer_tim=prefer_tim,
                match_tol_km=tim_match_tol_km,
            )

    validate_rows(
        locations,
        base,
        min_ai_vs_truth_km=min_ai_vs_truth_km,
        max_ai_vs_truth_km=max_ai_vs_truth_km,
    )

    rows: list[dict[str, Any]] = []
    for loc in locations:
        k = _row_key(loc["map_id"], loc["location_id"])
        alat, alon = base[k]
        rows.append(_ai_row(loc["map_id"], loc["location_id"], alat, alon))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"ai_guesses": rows}
    output_path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate ai_guesses.json for manifest assembly (IMP-082).")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: data/cache/<content-version>/ai_guesses.json)",
    )
    p.add_argument(
        "--content-version",
        default=None,
        help="Used for default output path when --output omitted",
    )
    p.add_argument(
        "--mode",
        required=True,
        choices=[
            "decoy_offset",
            "fixed_table",
            "random_seeded",
            "terramind_tim_jsonl",
            "terramind_tim_dir",
        ],
    )
    p.add_argument("--tim-export", type=Path, default=None, help="NDJSON lines (TiM / bundle exports)")
    p.add_argument("--tim-dir", type=Path, default=None, help="Directory of per-location *.json (requires map_id)")
    p.add_argument("--prefer-tim", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument(
        "--tim-match-tol-km",
        type=float,
        default=0.05,
        help="When --prefer-tim=false, max km between base and TiM to treat as matching",
    )
    p.add_argument("--delta-km", type=float, default=None)
    p.add_argument("--bearing-deg", type=float, default=None)
    p.add_argument("--csv", type=Path, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--min-km", type=float, default=None)
    p.add_argument("--max-km", type=float, default=None)
    p.add_argument(
        "--min-random-sep-km",
        type=float,
        default=1.0,
        help="random_seeded: minimum haversine separation from truth (rejection sampling)",
    )
    p.add_argument(
        "--min-ai-vs-truth-km",
        type=float,
        default=0.0,
        help="Reject if AI marker is closer than this to truth (0 disables)",
    )
    p.add_argument(
        "--max-ai-vs-truth-km",
        type=float,
        default=None,
        help="Optional maximum distance from truth (sanity check)",
    )
    args = p.parse_args(argv)

    cv = args.content_version or "dev"
    out_path = args.output
    if out_path is None:
        out_path = REPO_ROOT / "data" / "cache" / str(cv) / "ai_guesses.json"

    try:
        generate(
            catalog_root=args.catalog_root.resolve(),
            mode=args.mode,
            output_path=out_path.resolve(),
            tim_export=args.tim_export.resolve() if args.tim_export else None,
            tim_dir=args.tim_dir.resolve() if args.tim_dir else None,
            prefer_tim=bool(args.prefer_tim),
            tim_match_tol_km=float(args.tim_match_tol_km),
            delta_km=args.delta_km,
            bearing_deg=args.bearing_deg,
            csv_path=args.csv.resolve() if args.csv else None,
            seed=args.seed,
            min_km=args.min_km,
            max_km=args.max_km,
            min_sep_km=float(args.min_random_sep_km),
            min_ai_vs_truth_km=float(args.min_ai_vs_truth_km),
            max_ai_vs_truth_km=float(args.max_ai_vs_truth_km) if args.max_ai_vs_truth_km is not None else None,
        )
    except ValueError as e:
        msg = str(e)
        low = msg.lower()
        print(msg, file=sys.stderr)
        if "conflicting ai coordinate" in low:
            return EXIT_CONFLICT
        if args.mode == "fixed_table" or "csv" in low or "missing row for location_id" in low:
            return EXIT_CSV
        return EXIT_TIM_SCHEMA
    except OSError as e:
        print(str(e), file=sys.stderr)
        return EXIT_CSV

    print(out_path.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
