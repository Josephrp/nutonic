#!/usr/bin/env python3
"""
Validate data/catalog/ structure before expensive pipeline steps.

Normative: docs/scripts/SPEC-catalog-lint.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_ROOT = REPO_ROOT / "data" / "catalog"


@dataclass
class LintViolation:
    code: str
    message: str

    def json_line(self) -> str:
        return json.dumps({"code": self.code, "message": self.message}, ensure_ascii=False)


def _emit(v: LintViolation, json_errors: bool) -> None:
    if json_errors:
        print(v.json_line(), file=sys.stderr)
    else:
        print(v.message, file=sys.stderr)


def load_maps_index(catalog_root: Path) -> tuple[list[dict[str, Any]], list[LintViolation]]:
    maps_yaml = catalog_root / "maps.yaml"
    violations: list[LintViolation] = []
    if not maps_yaml.is_file():
        violations.append(LintViolation("missing_maps_yaml", f"Missing {maps_yaml}"))
        return [], violations
    try:
        data = yaml.safe_load(maps_yaml.read_text(encoding="utf-8")) or {}
    except Exception as e:
        violations.append(LintViolation("maps_yaml_parse", f"Cannot parse maps.yaml: {e}"))
        return [], violations
    maps = data.get("maps")
    if maps is None:
        maps = []
    if not isinstance(maps, list):
        violations.append(LintViolation("maps_type", "maps.yaml: 'maps' must be a list"))
        return [], violations
    seen: set[str] = set()
    for i, row in enumerate(maps):
        if not isinstance(row, dict):
            violations.append(LintViolation("map_row_type", f"maps[{i}] is not a mapping"))
            continue
        mid = row.get("map_id")
        if not mid:
            violations.append(LintViolation("map_id_missing", f"maps[{i}] missing map_id"))
            continue
        sid = str(mid)
        if sid in seen:
            violations.append(LintViolation("duplicate_map_id", f"Duplicate map_id: {sid}"))
        seen.add(sid)
    return [m for m in maps if isinstance(m, dict)], violations


def iter_location_files(catalog_root: Path) -> list[Path]:
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return []
    return sorted(loc_dir.glob("*.yaml"))


def lint_location_file(
    path: Path,
    repo_root: Path,
    *,
    seen_location_ids: set[str],
) -> list[LintViolation]:
    violations: list[LintViolation] = []
    stem = path.stem
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        violations.append(LintViolation("location_parse", f"{path}: parse error: {e}"))
        return violations
    if not isinstance(raw, dict):
        violations.append(LintViolation("location_shape", f"{path}: root must be a mapping"))
        return violations

    lid = raw.get("location_id")
    if lid is None:
        violations.append(LintViolation("location_id_missing", f"{path}: missing location_id"))
    else:
        ls = str(lid)
        if ls in seen_location_ids:
            violations.append(LintViolation("duplicate_location_id", f"Duplicate location_id {ls} (also in another file)"))
        seen_location_ids.add(ls)
        if ls != stem:
            violations.append(
                LintViolation(
                    "location_filename_mismatch",
                    f"{path}: filename {stem!r} should match location_id {ls!r}",
                )
            )

    for key in ("map_id", "truth_lat", "truth_lon"):
        if key not in raw:
            violations.append(LintViolation("location_key_missing", f"{path}: missing required key {key!r}"))

    try:
        lat = float(raw.get("truth_lat"))
        lon = float(raw.get("truth_lon"))
    except (TypeError, ValueError):
        violations.append(LintViolation("truth_coord_type", f"{path}: truth_lat/truth_lon must be numbers"))
    else:
        if not (-90.0 <= lat <= 90.0):
            violations.append(LintViolation("truth_lat_range", f"{path}: truth_lat out of range"))
        if not (-180.0 <= lon <= 180.0):
            violations.append(LintViolation("truth_lon_range", f"{path}: truth_lon out of range"))

    still = raw.get("still_source")
    if not isinstance(still, dict):
        violations.append(LintViolation("still_source_missing", f"{path}: still_source must be a mapping"))
    else:
        if "bundled_relative" in still:
            rel = still["bundled_relative"]
            if not isinstance(rel, str) or not rel.strip():
                violations.append(LintViolation("bundled_relative_invalid", f"{path}: bundled_relative must be non-empty string"))
            else:
                target = (repo_root / rel).resolve()
                try:
                    target.relative_to(repo_root.resolve())
                except ValueError:
                    violations.append(LintViolation("bundled_escape", f"{path}: bundled_relative escapes repo: {rel!r}"))
                else:
                    if not target.is_file():
                        violations.append(
                            LintViolation(
                                "bundled_missing",
                                f"{path}: bundled_relative does not exist: {rel}",
                            )
                        )
        elif "render_policy" in still:
            rp = still["render_policy"]
            if not isinstance(rp, dict):
                violations.append(LintViolation("render_policy_type", f"{path}: render_policy must be a mapping"))
        else:
            violations.append(
                LintViolation(
                    "still_source_shape",
                    f"{path}: still_source needs bundled_relative or render_policy",
                )
            )

    return violations


def lint_catalog(catalog_root: Path, repo_root: Path, *, verbose: bool, json_errors: bool) -> list[LintViolation]:
    catalog_root = catalog_root.resolve()
    repo_root = repo_root.resolve()
    all_v: list[LintViolation] = []

    maps, v_maps = load_maps_index(catalog_root)
    all_v.extend(v_maps)
    for v in v_maps:
        _emit(v, json_errors)

    loc_files = iter_location_files(catalog_root)
    if not loc_files and not any(v.code == "missing_maps_yaml" for v in v_maps):
        msg = f"No location YAML files under {catalog_root / 'locations'}"
        lv = LintViolation("no_locations", msg)
        all_v.append(lv)
        _emit(lv, json_errors)

    seen_ids: set[str] = set()
    for path in loc_files:
        if verbose:
            print(f"lint: checking {path.relative_to(catalog_root)}", file=sys.stderr)
        loc_v = lint_location_file(path, repo_root, seen_location_ids=seen_ids)
        for v in loc_v:
            _emit(v, json_errors)
        all_v.extend(loc_v)

    map_ids = {str(m.get("map_id")) for m in maps if m.get("map_id")}
    for mid in sorted(map_ids):
        loc_path = catalog_root / "locations" / f"{mid}.yaml"
        if not loc_path.is_file():
            lv = LintViolation("map_missing_location", f"maps.yaml references map_id {mid!r} but {loc_path.name} is missing")
            all_v.append(lv)
            _emit(lv, json_errors)

    return all_v


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lint data/catalog YAML")
    p.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    p.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json-errors", action="store_true", help="One JSON object per line on stderr")
    args = p.parse_args(argv)
    violations = lint_catalog(args.catalog_root, args.repo_root, verbose=args.verbose, json_errors=args.json_errors)
    if violations:
        if not args.json_errors:
            print(f"catalog_lint: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
