"""
TiM batch seed: merge Hub ``tim_batch_seed.json`` (from sv-lfm finalize) into a TiM YAML config.

``run_hf_hydration_full.py`` passes ``NUTONIC_HYDRATION_INCLUDED_LOCATION_IDS`` after Street View;
static hf_job YAML only lists 3–5 rows. The seed file restores **totality** for all included POIs.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping


TIM_BATCH_SEED_SCHEMA = "nutonic.tim_batch_seed.v1"


def load_tim_batch_seed(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be an object")
    ver = str(raw.get("schema_version") or "")
    if ver != TIM_BATCH_SEED_SCHEMA:
        raise ValueError(f"{path}: unsupported schema_version {ver!r} (expected {TIM_BATCH_SEED_SCHEMA!r})")
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: rows must be a non-empty list")
    return raw


def apply_tim_batch_seed_to_config(cfg: Mapping[str, Any], seed: Mapping[str, Any]) -> dict[str, Any]:
    """
    Return a deep copy of ``cfg`` with ``batch`` replaced by STAC rows built from seed rows.

    Per-row STAC fields (``rgb_mode``, ``s2_mode``, ``datetime``) are copied from the first
    existing ``cfg["batch"]`` row when present; otherwise minimal STAC defaults match hf_job YAMLs.
    """
    out = copy.deepcopy(dict(cfg))
    seed_rows = seed["rows"]
    assert isinstance(seed_rows, list)

    tmpl_row: dict[str, Any] = {}
    old_batch = out.get("batch")
    if isinstance(old_batch, list) and old_batch and isinstance(old_batch[0], dict):
        tmpl_row = dict(old_batch[0])

    rgb_mode = str(tmpl_row.get("rgb_mode") or "s2_rgb")
    s2_mode = str(tmpl_row.get("s2_mode") or "stac")
    row_dt = str(tmpl_row.get("datetime") or "").strip()
    inputs_block = out.get("inputs")
    inputs_dt = ""
    if isinstance(inputs_block, dict):
        inputs_dt = str(inputs_block.get("datetime") or "").strip()
    default_dt = row_dt or inputs_dt
    if not default_dt:
        raise ValueError("apply_tim_batch_seed_to_config: need datetime on seed template or inputs.datetime")

    new_batch: list[dict[str, Any]] = []
    for r in seed_rows:
        if not isinstance(r, dict):
            continue
        lid = str(r.get("location_id") or "").strip()
        mid = str(r.get("map_id") or lid).strip()
        if not lid:
            continue
        lat = r.get("truth_lat", r.get("lat"))
        lon = r.get("truth_lon", r.get("lon"))
        if lat is None or lon is None:
            raise ValueError(f"apply_tim_batch_seed_to_config: row missing lat/lon for location_id={lid!r}")
        new_batch.append(
            {
                "map_id": mid,
                "location_id": lid,
                "rgb_mode": rgb_mode,
                "lat": float(lat),
                "lon": float(lon),
                "datetime": str(r.get("datetime") or default_dt),
                "s2_mode": s2_mode,
            }
        )
    if not new_batch:
        raise ValueError("apply_tim_batch_seed_to_config: no usable rows after merge")
    out["batch"] = new_batch
    return out


def tim_batch_seed_rows_from_catalog(
    *,
    location_ids: list[str],
    catalog_locations_dir: Path,
) -> list[dict[str, Any]]:
    """Build seed ``rows`` in ``location_ids`` order (truth coords from catalog YAML)."""
    import yaml

    catalog_locations_dir = catalog_locations_dir.resolve()
    rows: list[dict[str, Any]] = []
    for lid in location_ids:
        p = catalog_locations_dir / f"{lid}.yaml"
        if not p.is_file():
            raise RuntimeError(f"tim_batch_seed: missing catalog YAML for location_id={lid!r}: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"tim_batch_seed: expected mapping in {p}")
        loc_id = str(raw.get("location_id") or lid).strip()
        map_id = str(raw.get("map_id") or loc_id).strip()
        try:
            lat = float(raw["truth_lat"])
            lon = float(raw["truth_lon"])
        except (KeyError, TypeError, ValueError) as e:
            raise RuntimeError(f"tim_batch_seed: {p} missing valid truth_lat/truth_lon") from e
        rows.append(
            {
                "map_id": map_id,
                "location_id": loc_id,
                "truth_lat": lat,
                "truth_lon": lon,
            }
        )
    return rows
