#!/usr/bin/env python3
"""
Rebuild ``data/catalog`` from a **materialized** HF hydration cache segment (no POI download tree).

HF Jobs finalize Street View under ``data/cache/<content_version>/`` and write
``build_stills/still_index.json`` with ``location_id``, ``map_id``, ``center_lat``,
``center_lon`` (same centers used for Mapbox stills = golden truth for assembly).

Use this when ``data/downloads/geoguessr_poi_*`` is absent but you already ran::

    python tools/materialize_hf_download_for_ship.py --hf-download-dir ... --content-version CV

Then::

    python tools/rebuild_catalog_from_hydration_cache.py --content-version CV
    python data/scripts/catalog_lint.py --catalog-root data/catalog
    python data/scripts/generate_ai_guess_fixture.py ...

If ``reports/hydration_included_location_ids.json`` exists, rows are restricted to that list
(intersection with ``still_index``; normally identical after sv-lfm finalize).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_included_ids(cache_cv: Path) -> set[str] | None:
    p = cache_cv / "reports" / "hydration_included_location_ids.json"
    if not p.is_file():
        return None
    doc = _load_json(p)
    lids = doc.get("location_ids")
    if not isinstance(lids, list):
        return None
    out = {str(x).strip() for x in lids if str(x).strip()}
    return out or None


def _apply_ranked_split_half(map_rows: list[dict[str, object]]) -> None:
    rows = sorted(map_rows, key=lambda m: str(m.get("map_id", "")))
    n = len(rows)
    cut = n // 2
    for i, m in enumerate(rows):
        m["ranked_pool"] = i >= cut


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Rebuild data/catalog from data/cache/<cv>/build_stills/still_index.json (no POI downloads).",
    )
    p.add_argument("--content-version", required=True, metavar="CV", help="Hydration content_version / cache dir name.")
    p.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help="Default: data/cache/<content-version>",
    )
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument(
        "--ranked-split",
        choices=("none", "half"),
        default="half",
        help="half: first n//2 maps ranked_pool false (matches catalog_import_poi).",
    )
    p.add_argument(
        "--engine-version",
        default="0.1.0",
        help="Written to maps.yaml (default matches typical shipped manifest).",
    )
    p.add_argument(
        "--run-catalog-lint",
        action="store_true",
        help="Run data/scripts/catalog_lint.py after write.",
    )
    args = p.parse_args(argv)

    cv = args.content_version.strip()
    cache_cv = (args.cache_root or (REPO_ROOT / "data" / "cache" / cv)).resolve()
    catalog_root = args.catalog_root.resolve()
    still_path = cache_cv / "build_stills" / "still_index.json"
    if not still_path.is_file():
        print(f"rebuild_catalog: missing {still_path}", file=sys.stderr)
        return 2

    data = _load_json(still_path)
    locs = data.get("locations")
    if not isinstance(locs, list) or not locs:
        print(f"rebuild_catalog: {still_path} has no locations[]", file=sys.stderr)
        return 2

    allow = _load_included_ids(cache_cv)

    rows: list[dict[str, object]] = []
    for raw in locs:
        if not isinstance(raw, dict):
            continue
        lid = str(raw.get("location_id") or "").strip()
        if not lid:
            continue
        if allow is not None and lid not in allow:
            continue
        mid = str(raw.get("map_id") or lid).strip()
        if mid != lid:
            print(
                f"rebuild_catalog: warning: still_index map_id={mid!r} != location_id={lid!r}; "
                f"using location_id for filenames and YAML ids (TiM/catalog join = poi id).",
                file=sys.stderr,
            )
            mid = lid
        try:
            lat = float(raw["center_lat"])
            lon = float(raw["center_lon"])
        except (KeyError, TypeError, ValueError):
            print(f"rebuild_catalog: skip {lid}: missing center_lat/center_lon", file=sys.stderr)
            continue
        still_source: dict[str, object] = {
            "render_policy": {
                "center_lat": lat,
                "center_lon": lon,
                "zoom": float(raw.get("zoom", 12.0)),
                "width_px": int(raw.get("width_px", 1280)),
                "height_px": int(raw.get("height_px", 1280)),
                "style": str(raw.get("style_id") or raw.get("style") or "satellite-v9"),
            }
        }
        loc_yaml: dict[str, object] = {
            "location_id": lid,
            "map_id": mid,
            "truth_lat": lat,
            "truth_lon": lon,
            "assist_level": "standard",
            "still_source": still_source,
        }
        rows.append({"lid": lid, "yaml": loc_yaml, "map_row": _map_row(mid)})

    if not rows:
        print("rebuild_catalog: no locations after filter", file=sys.stderr)
        return 3

    rows.sort(key=lambda r: str(r["lid"]))
    loc_dir = catalog_root / "locations"
    loc_dir.mkdir(parents=True, exist_ok=True)
    map_rows = [r["map_row"] for r in rows]
    if args.ranked_split == "half":
        _apply_ranked_split_half(map_rows)

    for r in rows:
        ypath = loc_dir / f"{r['lid']}.yaml"
        ypath.write_text(
            yaml.safe_dump(r["yaml"], sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
            newline="\n",
        )

    maps_doc: dict[str, object] = {
        "content_version": cv,
        "engine_version": str(args.engine_version),
        "maps": sorted(map_rows, key=lambda m: str(m.get("map_id", ""))),
    }
    (catalog_root / "maps.yaml").write_text(
        yaml.safe_dump(maps_doc, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
        newline="\n",
    )
    print(f"rebuild_catalog: wrote {len(rows)} location(s) under {loc_dir}", flush=True)
    print(f"rebuild_catalog: wrote {catalog_root / 'maps.yaml'}", flush=True)

    if args.run_catalog_lint:
        rc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "data" / "scripts" / "catalog_lint.py"), "--catalog-root", str(catalog_root)],
            cwd=str(REPO_ROOT),
            check=False,
        ).returncode
        if rc != 0:
            return int(rc)
    else:
        print("rebuild_catalog: next: python data/scripts/catalog_lint.py --catalog-root data/catalog", flush=True)
    return 0


def _map_row(map_id: str) -> dict[str, object]:
    return {
        "map_id": map_id,
        "title": f"POI {map_id}",
        "local_only": True,
        "ranked_pool": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
