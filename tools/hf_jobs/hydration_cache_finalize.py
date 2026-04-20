"""
Drop incomplete POIs from a hydration cache segment after Street View batching.

Failed Google / pano / LFM steps are recorded in ``reports/streetview_failures.json``.
We remove those (and any still-index row without a matching ``streetview/<id>.json``)
from stills, geo, hints, Street View JSON, catalog YAML, then rewrite ``still_index.json``
and emit ``reports/hydration_included_location_ids.json`` for downstream TiM / narrative jobs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "nutonic.hydration_included_pois.v1"


def _write_tim_batch_seed(
    *,
    cache_cv: Path,
    catalog_locations_dir: Path,
    content_version: str,
    location_ids: list[str],
) -> None:
    """Emit STAC seed coordinates for TiM so the GPU job matches finalized Street View POIs."""
    from tim_batch_seed import TIM_BATCH_SEED_SCHEMA, tim_batch_seed_rows_from_catalog

    if not location_ids:
        return
    rows = tim_batch_seed_rows_from_catalog(
        location_ids=location_ids,
        catalog_locations_dir=catalog_locations_dir,
    )
    payload = {
        "schema_version": TIM_BATCH_SEED_SCHEMA,
        "content_version": content_version,
        "rows": rows,
    }
    rep = cache_cv / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "tim_batch_seed.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _still_index_location_ids(still_index_path: Path) -> list[str]:
    if not still_index_path.is_file():
        return []
    data = json.loads(still_index_path.read_text(encoding="utf-8"))
    locs = data.get("locations")
    if not isinstance(locs, list):
        return []
    out: list[str] = []
    for row in locs:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("location_id") or row.get("map_id") or "").strip()
        if lid:
            out.append(lid)
    return out


def _read_failure_ids(rep_dir: Path) -> set[str]:
    p = rep_dir / "streetview_failures.json"
    if not p.is_file():
        return set()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"hydration_cache_finalize: invalid JSON in {p}", file=sys.stderr)
        return set()
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            lid = str(item.get("location_id") or "").strip()
            if lid:
                out.add(lid)
    return out


def _rewrite_still_index(still_index_path: Path, *, keep: set[str]) -> None:
    if not still_index_path.is_file():
        return
    data = json.loads(still_index_path.read_text(encoding="utf-8"))
    locs = data.get("locations")
    if not isinstance(locs, list):
        return
    filtered = [row for row in locs if isinstance(row, dict) and str(row.get("location_id", "")).strip() in keep]
    data["locations"] = filtered
    still_index_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _unlink_silent(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def finalize_hydration_cache_post_streetview(
    *,
    cache_cv: Path,
    catalog_locations_dir: Path,
    content_version: str,
) -> list[str]:
    """
    Remove POIs that failed Street View (or lack a streetview JSON) from cache + catalog.

    Returns sorted ``location_id`` values that remain (possibly empty).
    """
    cache_cv = cache_cv.resolve()
    catalog_locations_dir = catalog_locations_dir.resolve()
    still_index = cache_cv / "build_stills" / "still_index.json"
    planned = _still_index_location_ids(still_index)
    if not planned:
        print(
            f"hydration_cache_finalize: no locations in {still_index} — skipping prune",
            file=sys.stderr,
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "content_version": content_version,
            "location_ids": [],
            "excluded": [],
        }
        (cache_cv / "reports").mkdir(parents=True, exist_ok=True)
        (cache_cv / "reports" / "hydration_included_location_ids.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return []

    rep_dir = cache_cv / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    failed = _read_failure_ids(rep_dir)
    sv_dir = cache_cv / "streetview"
    missing_sv = {lid for lid in planned if not (sv_dir / f"{lid}.json").is_file()}
    excluded = failed | missing_sv

    prune_events: list[dict[str, Any]] = []
    for lid in sorted(excluded):
        reason = "streetview_batch_failure" if lid in failed else "missing_streetview_json"
        prune_events.append({"location_id": lid, "reason": reason})
        _unlink_silent(cache_cv / "streetview" / f"{lid}.json")
        _unlink_silent(cache_cv / "geo_context" / f"{lid}.json")
        _unlink_silent(cache_cv / "useful_hints" / f"{lid}.json")
        _unlink_silent(cache_cv / "build_stills" / "stills" / f"{lid}.jpg")
        _unlink_silent(cache_cv / "build_stills" / "stills" / f"{lid}.meta.json")
        _unlink_silent(catalog_locations_dir / f"{lid}.yaml")

    included_set = set(planned) - excluded
    _rewrite_still_index(still_index, keep=included_set)
    included = sorted(included_set)

    # No dangling failure records for POIs we removed from the shipped cache.
    (rep_dir / "streetview_failures.json").write_text("[]\n", encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "content_version": content_version,
        "location_ids": included,
        "excluded": prune_events,
    }
    (rep_dir / "hydration_included_location_ids.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if included:
        _write_tim_batch_seed(
            cache_cv=cache_cv,
            catalog_locations_dir=catalog_locations_dir,
            content_version=content_version,
            location_ids=included,
        )
    if excluded:
        print(
            f"hydration_cache_finalize: excluded {len(excluded)} POI(s) from cache upload; "
            f"{len(included)} remaining ({', '.join(included)})",
            file=sys.stderr,
        )
    return included
