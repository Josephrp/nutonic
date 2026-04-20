#!/usr/bin/env python3
"""
Build ranked clue pack JSON (no golden WGS84) from manifest.full.json + maps.yaml flags.

Normative: docs/scripts/SPEC-assemble-ranked-clue-pack.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_INPUT = 2
EXIT_LEAK = 12


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _load_maps_ranked_flags(catalog_root: Path) -> dict[str, bool]:
    maps_yaml = catalog_root / "maps.yaml"
    raw = yaml.safe_load(maps_yaml.read_text(encoding="utf-8")) or {}
    rows = raw.get("maps") or []
    out: dict[str, bool] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("map_id")
        if not mid:
            continue
        out[str(mid)] = bool(row.get("ranked_pool", False))
    return out


def _assert_no_golden_leak(obj: Any, path: str = "$") -> None:
    """Fail closed if serialized JSON would expose golden keys inside clue payloads."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in ("truth_lat", "truth_lon"):
                raise ValueError(f"Golden leak at {path}.{ks}")
            _assert_no_golden_leak(v, f"{path}.{ks}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_golden_leak(v, f"{path}[{i}]")


def build_ranked_pack(manifest: dict[str, Any], ranked_by_map: dict[str, bool]) -> dict[str, Any]:
    clues: list[dict[str, Any]] = []
    locs = manifest.get("locations") or []
    if not isinstance(locs, list):
        raise ValueError("manifest.locations must be a list")

    for loc in locs:
        if not isinstance(loc, dict):
            continue
        mid = str(loc.get("map_id", ""))
        if not ranked_by_map.get(mid):
            continue
        lid = str(loc.get("location_id", ""))
        clue: dict[str, Any] = {
            "ai_marker_phase_enabled": bool(loc.get("ai_marker_phase_enabled", True)),
            "location_id": lid,
            "map_id": mid,
            "play_budget_ms": loc.get("play_budget_ms"),
            "still_bundled_resource": loc.get("still_bundled_resource"),
            "still_bundle_id": loc.get("still_bundle_id"),
            "useful_hints": loc.get("useful_hints"),
        }
        for meta_key in (
            "useful_hints_metadata",
            "useful_hints_validation",
            "streetview_hint_pack_validation",
            "streetview_assist_narrative_validation",
            "streetview_assist_narrative_metadata",
        ):
            if loc.get(meta_key) is not None:
                clue[meta_key] = loc[meta_key]
        if loc.get("streetview_hint_pack") is not None:
            clue["streetview_hint_pack"] = loc.get("streetview_hint_pack")
        if loc.get("streetview_assist_narrative") is not None:
            clue["streetview_assist_narrative"] = loc.get("streetview_assist_narrative")
        if loc.get("satellite_caption_sidecar") is not None:
            clue["satellite_caption_sidecar"] = loc.get("satellite_caption_sidecar")
        clues.append(clue)

    clues.sort(key=lambda c: (c["map_id"], c["location_id"]))

    clue_keys = {(c["map_id"], c["location_id"]) for c in clues}
    ai_all = manifest.get("ai_guesses") or []
    ai_out: list[dict[str, Any]] = []
    if isinstance(ai_all, list):
        for row in ai_all:
            if not isinstance(row, dict):
                continue
            key = (str(row.get("map_id")), str(row.get("location_id")))
            if key in clue_keys:
                ai_out.append(
                    {
                        "ai_lat": float(row["ai_lat"]),
                        "ai_lon": float(row["ai_lon"]),
                        "location_id": key[1],
                        "map_id": key[0],
                    }
                )
    ai_out.sort(key=lambda r: (r["map_id"], r["location_id"]))

    pack = {
        "ai_guesses": ai_out,
        "clues": clues,
        "schema_version": "nutonic.ranked_clue_pack.v1",
    }
    _assert_no_golden_leak(pack)
    return pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble ranked clue pack JSON (no golden coordinates).")
    p.add_argument("--manifest", type=Path, required=True, help="Path to manifest.full.json")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)

    manifest_path = args.manifest.resolve()
    if not manifest_path.is_file():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return EXIT_INPUT

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ranked = _load_maps_ranked_flags(args.catalog_root.resolve())
        pack = build_ranked_pack(manifest, ranked)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return EXIT_LEAK
    except OSError as e:
        print(str(e), file=sys.stderr)
        return EXIT_INPUT

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for clue in pack["clues"]:
        mid = clue["map_id"]
        slice_path = out_dir / "ranked_clues" / f"{mid}.json"
        slice_path.parent.mkdir(parents=True, exist_ok=True)
        slice_path.write_text(_canonical_json(clue) + "\n", encoding="utf-8")

    (out_dir / "ranked_clue_pack.json").write_text(_canonical_json(pack) + "\n", encoding="utf-8")
    print((out_dir / "ranked_clue_pack.json").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
