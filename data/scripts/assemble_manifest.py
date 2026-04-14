#!/usr/bin/env python3
"""
Merge catalog rows, still index, useful_hints, and optional ai_guesses into CacheManifest JSON.

Normative: docs/scripts/SPEC-assemble-manifest.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_INPUT = 2
EXIT_CATALOG_LINT = 1
EXIT_VALIDATE = 11


def _canonical_json(obj: Any) -> str:
    """Match server ETag-friendly serialization (`nutonic_server/main.py`)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected YAML mapping at root")
    return raw


def _list_locations(catalog_root: Path) -> list[Path]:
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return []
    return sorted(loc_dir.glob("*.yaml"))


def _load_still_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Still index not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    locs = data.get("locations")
    if not isinstance(locs, list):
        raise ValueError(f"{path}: expected 'locations' array")
    out: dict[str, dict[str, Any]] = {}
    for row in locs:
        if not isinstance(row, dict):
            continue
        lid = row.get("location_id")
        if lid is not None:
            out[str(lid)] = row
    return out


def _load_useful_hints_dir(d: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            continue
        lid = obj.get("location_id")
        if lid is not None:
            out[str(lid)] = obj
    return out


def _load_streetview_dir(d: Path | None) -> dict[str, dict[str, Any]]:
    """Per ``location_id`` merged row from ``batch_streetview_hints`` JSON files."""
    if d is None or not d.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            continue
        lid = obj.get("location_id")
        if lid is not None:
            out[str(lid)] = obj
    return out


def _load_ai_guesses(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("ai_guesses")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{path}: 'ai_guesses' must be a list")
    return [r for r in rows if isinstance(r, dict)]


def _map_summaries_for_manifest(maps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAPI `MapSummary` keys only."""
    out: list[dict[str, Any]] = []
    for row in sorted(maps_rows, key=lambda m: str(m.get("map_id", ""))):
        mid = row.get("map_id")
        title = row.get("title")
        if not mid or not title:
            continue
        item: dict[str, Any] = {
            "map_id": str(mid),
            "title": str(title),
        }
        if row.get("engine_version") is not None:
            item["engine_version"] = str(row["engine_version"])
        else:
            item["engine_version"] = None
        if row.get("content_version") is not None:
            item["content_version"] = str(row["content_version"])
        else:
            item["content_version"] = None
        out.append(item)
    return out


def _normalize_hints_for_manifest(hints: dict[str, Any]) -> dict[str, Any]:
    """Emit UsefulHintsTiers: optional tiers omitted when empty."""
    keys = [f"tier_{i}" for i in range(1, 7)]
    out: dict[str, Any] = {}
    for k in keys:
        v = hints.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s and k in ("tier_4", "tier_5", "tier_6"):
            continue
        out[k] = s
    return out


def assemble_manifest(
    *,
    catalog_root: Path,
    repo_root: Path,
    still_index_path: Path,
    useful_hints_dir: Path,
    streetview_dir: Path | None,
    ai_guesses_path: Path | None,
    tier_policy_path: Path,
    output_dir: Path,
    content_version: str | None,
    engine_version: str | None,
    expose_public_round_truth: bool,
    skip_catalog_lint: bool,
    skip_hint_validate: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Returns (manifest_full, manifest_public) as plain dicts.
    Raises ValueError on validation failures.
    """
    from catalog_lint import lint_catalog
    from validate_hint_strings import HintPolicy, validate_caption_text, validate_hints

    catalog_root = catalog_root.resolve()
    repo_root = repo_root.resolve()

    if not skip_catalog_lint:
        violations = lint_catalog(catalog_root, repo_root, verbose=False, json_errors=False)
        if violations:
            raise ValueError("catalog_lint failed: " + "; ".join(v.message for v in violations))

    maps_yaml = catalog_root / "maps.yaml"
    root = _load_yaml_mapping(maps_yaml)
    maps_rows = root.get("maps") or []
    if not isinstance(maps_rows, list):
        raise ValueError("maps.yaml: 'maps' must be a list")

    cv = content_version or root.get("content_version")
    if cv is None or str(cv).strip() == "":
        raise ValueError("content_version missing (set in maps.yaml or pass --content-version)")
    cv_s = str(cv)

    ev_manifest = engine_version
    if ev_manifest is None and root.get("engine_version") is not None:
        ev_manifest = str(root["engine_version"])

    still_by_loc = _load_still_index(still_index_path)
    hints_by_loc = _load_useful_hints_dir(useful_hints_dir)
    streetview_by_loc = _load_streetview_dir(streetview_dir.resolve() if streetview_dir else None)
    ai_rows = _load_ai_guesses(ai_guesses_path)
    hint_policy = HintPolicy.from_yaml_path(tier_policy_path)

    locations_out: list[dict[str, Any]] = []
    for ypath in _list_locations(catalog_root):
        loc = _load_yaml_mapping(ypath)
        lid = str(loc.get("location_id") or ypath.stem)
        mid = str(loc.get("map_id") or lid)
        assist = str(loc.get("assist_level") or "standard").strip().lower()

        lat = float(loc["truth_lat"])
        lon = float(loc["truth_lon"])

        still_rec = still_by_loc.get(lid)
        if still_rec is None:
            raise ValueError(f"Missing still_index entry for location_id={lid}")

        useful: dict[str, Any] | None = None
        if assist == "none":
            useful = None
        else:
            hint_obj = hints_by_loc.get(lid)
            if hint_obj is None:
                raise ValueError(f"Missing useful_hints JSON for location_id={lid}")
            uh = hint_obj.get("useful_hints")
            if not isinstance(uh, dict):
                raise ValueError(f"{lid}: useful_hints object missing")
            useful = _normalize_hints_for_manifest(uh)
            if not skip_hint_validate:
                payload = {"useful_hints": dict(useful), "assist_level": assist}
                viol = validate_hints(payload, hint_policy)
                if viol:
                    raise ValueError(
                        f"validate_hints failed for {lid}: " + "; ".join(v.format_line() for v in viol)
                    )

        row: dict[str, Any] = {
            "map_id": mid,
            "location_id": lid,
            "truth_lat": lat,
            "truth_lon": lon,
            "ruleset_version": str(loc["ruleset_version"]) if loc.get("ruleset_version") else "nutonic.ruleset.v1",
            "still_bundle_id": still_rec.get("still_bundle_id"),
            "still_bundled_resource": still_rec.get("still_bundled_resource"),
            "still_http_url": str(loc["still_http_url"]) if loc.get("still_http_url") else None,
            "useful_hints": useful,
            "play_budget_ms": int(loc["play_budget_ms"]) if loc.get("play_budget_ms") is not None else 180_000,
            "ai_marker_phase_enabled": bool(loc.get("ai_marker_phase_enabled", True)),
        }

        sv_doc = streetview_by_loc.get(lid)
        if isinstance(sv_doc, dict):
            pack = sv_doc.get("streetview_hint_pack")
            if pack is not None:
                if not isinstance(pack, list):
                    raise ValueError(f"{lid}: streetview_hint_pack must be a list")
                for j, item in enumerate(pack):
                    if not isinstance(item, dict):
                        raise ValueError(f"{lid}: streetview_hint_pack[{j}] must be an object")
                    txt = str(item.get("text", "")).strip()
                    if not txt:
                        raise ValueError(f"{lid}: streetview_hint_pack[{j}].text empty")
                    if not skip_hint_validate:
                        viol = validate_caption_text(txt, max_len=480, path=f"{lid}.streetview_hint_pack[{j}].text")
                        if viol:
                            raise ValueError(
                                f"validate_caption_text failed for {lid} pack[{j}]: "
                                + "; ".join(v.format_line() for v in viol)
                            )
                row["streetview_hint_pack"] = pack
            narr = sv_doc.get("streetview_assist_narrative")
            if narr is not None and str(narr).strip():
                ns = str(narr).strip()
                if not skip_hint_validate:
                    viol = validate_caption_text(ns, max_len=900, path=f"{lid}.streetview_assist_narrative")
                    if viol:
                        raise ValueError(
                            f"validate_caption_text failed for {lid} narrative: "
                            + "; ".join(v.format_line() for v in viol)
                        )
                row["streetview_assist_narrative"] = ns
            sc = sv_doc.get("satellite_caption_sidecar")
            if isinstance(sc, dict):
                row["satellite_caption_sidecar"] = sc

        locations_out.append(row)

    locations_out.sort(key=lambda r: (r["map_id"], r["location_id"]))

    ai_filtered: list[dict[str, Any]] = []
    loc_keys = {(r["map_id"], r["location_id"]) for r in locations_out}
    for g in ai_rows:
        key = (str(g.get("map_id")), str(g.get("location_id")))
        if key in loc_keys:
            ai_filtered.append(
                {
                    "map_id": key[0],
                    "location_id": key[1],
                    "ai_lat": float(g["ai_lat"]),
                    "ai_lon": float(g["ai_lon"]),
                }
            )
    ai_filtered.sort(key=lambda r: (r["map_id"], r["location_id"]))

    manifest_full: dict[str, Any] = {
        "ai_guesses": ai_filtered,
        "content_version": cv_s,
        "engine_version": ev_manifest,
        "locations": locations_out,
        "maps": _map_summaries_for_manifest([m for m in maps_rows if isinstance(m, dict)]),
    }

    manifest_public = json.loads(_canonical_json(manifest_full))
    if not expose_public_round_truth:
        manifest_public["locations"] = []
        manifest_public["ai_guesses"] = []

    return manifest_full, manifest_public


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble CacheManifest JSON (full + public).")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    p.add_argument("--still-index", type=Path, help="Path to still_index.json (from render_mapbox_still)")
    p.add_argument(
        "--useful-hints-dir",
        type=Path,
        help="Directory of per-location useful_hints *.json (from compile_useful_hint_tiers)",
    )
    p.add_argument(
        "--streetview-dir",
        type=Path,
        default=None,
        help="Optional directory of batch_streetview_hints per-location *.json (streetview_hint_pack)",
    )
    p.add_argument("--ai-guesses", type=Path, default=None, help="Optional ai_guesses.json envelope")
    p.add_argument("--tier-policy", type=Path, default=_SCRIPTS / "tier_policy.default.yaml")
    p.add_argument("--output-dir", type=Path, required=True, help="Writes manifest.full.json and manifest.public.json")
    p.add_argument("--content-version", default=None, help="Override maps.yaml content_version")
    p.add_argument("--engine-version", default=None, help="Top-level manifest engine_version")
    p.add_argument(
        "--expose-public-round-truth",
        action="store_true",
        help="Include locations/ai_guesses in manifest.public.json (lab only)",
    )
    p.add_argument("--skip-catalog-lint", action="store_true", help="Skip catalog_lint (tests/debug only).")
    p.add_argument("--skip-hint-validate", action="store_true", help="Skip validate_hints (debug only).")
    args = p.parse_args(argv)

    still_index = args.still_index
    hints_dir = args.useful_hints_dir
    if still_index is None or hints_dir is None:
        print("--still-index and --useful-hints-dir are required", file=sys.stderr)
        return EXIT_INPUT

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        full_doc, pub_doc = assemble_manifest(
            catalog_root=args.catalog_root.resolve(),
            repo_root=args.repo_root.resolve(),
            still_index_path=still_index.resolve(),
            useful_hints_dir=hints_dir.resolve(),
            streetview_dir=args.streetview_dir.resolve() if args.streetview_dir else None,
            ai_guesses_path=args.ai_guesses.resolve() if args.ai_guesses else None,
            tier_policy_path=args.tier_policy.resolve(),
            output_dir=out_dir,
            content_version=args.content_version,
            engine_version=args.engine_version,
            expose_public_round_truth=bool(args.expose_public_round_truth),
            skip_catalog_lint=bool(args.skip_catalog_lint),
            skip_hint_validate=bool(args.skip_hint_validate),
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_INPUT
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return EXIT_VALIDATE

    (out_dir / "manifest.full.json").write_text(_canonical_json(full_doc) + "\n", encoding="utf-8")
    (out_dir / "manifest.public.json").write_text(_canonical_json(pub_doc) + "\n", encoding="utf-8")
    print(out_dir.joinpath("manifest.full.json").as_posix())
    print(out_dir.joinpath("manifest.public.json").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
