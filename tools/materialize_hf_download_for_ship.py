#!/usr/bin/env python3
"""
Materialize a Hugging Face **dataset** snapshot (from ``tools/download_hydration_outputs.py``)
into ``data/cache/<content_version>/`` so repo scripts match the **HF Jobs** layout.

HF Jobs upload ``data/cache/<cv>/`` to ``runs/<cv>/`` on the Hub; ``snapshot_download`` mirrors
that under e.g. ``data/cache/hf_downloads/<repo_sanitized>/runs/<cv>/``. This tool copies that
slice into the canonical ``data/cache/<cv>/`` tree expected by:

- ``data/scripts/assemble_manifest.py`` (``--still-index``, ``--useful-hints-dir``, …)
- ``data/scripts/generate_ai_guess_fixture.py`` (TiM JSONL under ``tim/tim_export.jsonl``)

It also:

- Rewrites ``build_stills/still_index.json`` so ``still_bundled_resource`` is
  ``files/maps/<location_id>.jpg`` (Compose ``Res.readBytes`` + ``validate_shipped_compose_resources``).
- Copies JPEGs from ``build_stills/stills/*.jpg`` into
  ``nutonic/shared/src/commonMain/composeResources/files/maps/``.
- Optionally prunes ``data/catalog/locations/*.yaml`` + ``maps.yaml`` to match
  ``reports/hydration_included_location_ids.json`` (sv-lfm finalize drops failed POIs on the Job,
  but that pruned catalog is **not** re-uploaded in the cache folder — local catalog must match).

Does **not** re-submit HF Jobs. Pair with the same ``--content-version`` you passed to
``tools/run_full_hydration.py``.

Example::

    python tools/materialize_hf_download_for_ship.py \\
      --hf-download-dir data/cache/hf_downloads/NuTonic__hydration-test-9 \\
      --content-version hf-test-5poi-20260418 \\
      --prune-catalog

If ``data/catalog/locations`` does not exist yet, import POIs **first** (same ``--poi-limit`` /
``--ranked-split`` as the HF Job), then prune to the finalized Street View set::

    python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12 \\
      --catalog-root data/catalog --content-version hf-test-5poi-20260418 \\
      --ranked-split half --poi-limit 20 --force

    python tools/materialize_hf_download_for_ship.py --prune-catalog-only \\
      --content-version hf-test-5poi-20260418
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_MAPS = (
    REPO_ROOT
    / "nutonic"
    / "shared"
    / "src"
    / "commonMain"
    / "composeResources"
    / "files"
    / "maps"
)


def _copy_tree_merge(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"Missing source directory: {src}")
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)


def _load_included_location_ids(cache_cv: Path) -> list[str] | None:
    p = cache_cv / "reports" / "hydration_included_location_ids.json"
    if not p.is_file():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    lids = doc.get("location_ids")
    if not isinstance(lids, list):
        return None
    return [str(x).strip() for x in lids if str(x).strip()]


def _normalize_still_index(cache_cv: Path) -> int:
    p = cache_cv / "build_stills" / "still_index.json"
    if not p.is_file():
        print(f"materialize: no still_index at {p}", file=sys.stderr)
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    locs = data.get("locations")
    if not isinstance(locs, list):
        return 0
    changed = 0
    for row in locs:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("location_id") or "").strip()
        if not lid:
            continue
        want = f"files/maps/{lid}.jpg"
        if row.get("still_bundled_resource") != want:
            row["still_bundled_resource"] = want
            changed += 1
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return changed


def _copy_stills_to_compose(cache_cv: Path) -> int:
    meta_stills = cache_cv / "build_stills" / "stills"
    if not meta_stills.is_dir():
        return 0
    _COMPOSE_MAPS.mkdir(parents=True, exist_ok=True)
    n = 0
    for jp in sorted(meta_stills.glob("*.jpg")):
        shutil.copy2(jp, _COMPOSE_MAPS / jp.name)
        n += 1
    return n


def _prune_catalog(
    included: list[str], *, catalog_root: Path, dry_run: bool
) -> tuple[bool, str | None]:
    """
    Returns (ok, error_message). ok False when locations dir missing or nothing to prune and
    caller should surface catalog_import instructions.
    """
    catalog_root = catalog_root.resolve()
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return False, f"no catalog locations dir: {loc_dir}"
    keep = set(included)
    removed: list[str] = []
    for y in sorted(loc_dir.glob("*.yaml")):
        stem = y.stem
        if stem not in keep:
            removed.append(stem)
            if not dry_run:
                y.unlink(missing_ok=True)
    maps_yaml = catalog_root / "maps.yaml"
    if maps_yaml.is_file():
        root = yaml.safe_load(maps_yaml.read_text(encoding="utf-8")) or {}
        maps = root.get("maps")
        if isinstance(maps, list):
            filtered = [m for m in maps if isinstance(m, dict) and str(m.get("map_id", "")).strip() in keep]
            if len(filtered) != len(maps):
                root["maps"] = filtered
                if not dry_run:
                    maps_yaml.write_text(
                        yaml.safe_dump(root, sort_keys=False, allow_unicode=True, default_flow_style=False),
                        encoding="utf-8",
                        newline="\n",
                    )
    action = "Would remove" if dry_run else "Removed"
    if removed:
        print(f"materialize: {action} {len(removed)} catalog location(s) not in hydration manifest", flush=True)
    elif not dry_run:
        print("materialize: catalog already matches hydration manifest (no extra locations removed)", flush=True)
    return True, None


def _print_ship_next_steps(dst: Path, cv: str) -> None:
    print("\nNext (from repo root):", flush=True)
    print(
        "  # No local data/downloads/geoguessr_* (POI on Hub): rebuild catalog from still_index:\n"
        f"  python tools/rebuild_catalog_from_hydration_cache.py --content-version {cv} --run-catalog-lint",
        flush=True,
    )
    tim_jsonl = dst / "tim" / "tim_export.jsonl"
    if not tim_jsonl.is_file():
        print(
            f"materialize: note: no TiM export at {tim_jsonl} — omit --tim-export or use decoy AI fixture; "
            "see data/scripts/generate_ai_guess_fixture.py",
            file=sys.stderr,
        )
    print(
        "  python data/scripts/generate_ai_guess_fixture.py \\\n"
        f"    --mode terramind_tim_jsonl --tim-export {tim_jsonl.as_posix()} \\\n"
        f"    --content-version {cv} --min-ai-vs-truth-km 0",
        flush=True,
    )
    print(
        "  python data/scripts/assemble_manifest.py \\\n"
        "    --catalog-root data/catalog \\\n"
        f"    --still-index {dst / 'build_stills' / 'still_index.json'} \\\n"
        f"    --useful-hints-dir {dst / 'useful_hints'} \\\n"
        f"    --streetview-dir {dst / 'streetview'} \\\n"
        f"    --ai-guesses {dst / 'ai_guesses.json'} \\\n"
        f"    --output-dir {dst}",
        flush=True,
    )
    print(
        "  python data/scripts/assemble_ranked_clue_pack.py \\\n"
        f"    --manifest {dst / 'manifest.full.json'} \\\n"
        "    --catalog-root data/catalog \\\n"
        f"    --output-dir {dst}",
        flush=True,
    )
    ship_manifest = (
        REPO_ROOT
        / "nutonic"
        / "shared"
        / "src"
        / "commonMain"
        / "composeResources"
        / "files"
        / "cache"
        / "manifest.full.json"
    )
    ship_ranked = (
        REPO_ROOT
        / "nutonic"
        / "shared"
        / "src"
        / "commonMain"
        / "composeResources"
        / "files"
        / "ranked"
        / "ranked_clue_pack.json"
    )
    print(
        f"  copy / merge: {dst / 'manifest.full.json'} -> {ship_manifest}\n"
        f"                {dst / 'ranked_clue_pack.json'} -> {ship_ranked}",
        flush=True,
    )
    print("  python data/scripts/sync_server_catalog.py --write", flush=True)
    print("  ./gradlew :shared:validateCatalog   # or full build", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Copy HF hydration snapshot into data/cache/<cv>/ and prep still paths + compose maps.",
    )
    p.add_argument(
        "--hf-download-dir",
        type=Path,
        default=None,
        help="Local snapshot root (e.g. data/cache/hf_downloads/NuTonic__hydration-test-9). "
        "Omit when using --prune-catalog-only.",
    )
    p.add_argument("--content-version", required=True, help="Same CONTENT_VERSION as the HF Jobs run.")
    p.add_argument(
        "--catalog-root",
        type=Path,
        default=REPO_ROOT / "data" / "catalog",
        help="Used with --prune-catalog (default: data/catalog).",
    )
    p.add_argument(
        "--prune-catalog",
        action="store_true",
        help="Remove catalog locations not listed in reports/hydration_included_location_ids.json.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="With --prune-catalog, print actions without deleting or rewriting maps.yaml.",
    )
    p.add_argument(
        "--prune-catalog-only",
        action="store_true",
        help="Only prune data/catalog to reports/hydration_included_location_ids.json under data/cache/<cv>/. "
        "Use after catalog_import_poi. Does not copy from hf_downloads.",
    )
    args = p.parse_args(argv)

    cv = args.content_version.strip()
    dst = REPO_ROOT / "data" / "cache" / cv

    if args.prune_catalog_only:
        inc = _load_included_location_ids(dst)
        if not inc:
            print(
                f"materialize: no location_ids in {dst / 'reports' / 'hydration_included_location_ids.json'}",
                file=sys.stderr,
            )
            return 3
        ok, err = _prune_catalog(inc, catalog_root=args.catalog_root, dry_run=bool(args.dry_run))
        if not ok:
            print(
                f"materialize: {err}\n"
                "Import POIs first, then re-run with --prune-catalog-only, e.g.:\n"
                "  python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12 \\\n"
                f"    --catalog-root data/catalog --content-version {cv} --ranked-split half --poi-limit 20 --force",
                file=sys.stderr,
            )
            return 4
        _print_ship_next_steps(dst, cv)
        return 0

    if args.hf_download_dir is None:
        print("materialize: --hf-download-dir is required unless --prune-catalog-only", file=sys.stderr)
        return 2

    hf_root = args.hf_download_dir.resolve()
    src = hf_root / "runs" / cv

    try:
        _copy_tree_merge(src, dst)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"materialize: copied {src} -> {dst}", flush=True)
    n_norm = _normalize_still_index(dst)
    print(f"materialize: normalized {n_norm} still_index still_bundled_resource row(s)", flush=True)
    n_jpg = _copy_stills_to_compose(dst)
    print(f"materialize: copied {n_jpg} still JPEG(s) -> {_COMPOSE_MAPS}", flush=True)

    if args.prune_catalog:
        inc = _load_included_location_ids(dst)
        if not inc:
            print(
                "materialize: --prune-catalog set but hydration_included_location_ids.json missing or empty",
                file=sys.stderr,
            )
            return 3
        ok, err = _prune_catalog(inc, catalog_root=args.catalog_root, dry_run=bool(args.dry_run))
        if not ok:
            print(
                f"materialize: {err}\n"
                "Run catalog import (same --poi-limit as the Job), then:\n"
                f"  python tools/materialize_hf_download_for_ship.py --prune-catalog-only --content-version {cv}",
                file=sys.stderr,
            )
            return 4

    _print_ship_next_steps(dst, cv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
