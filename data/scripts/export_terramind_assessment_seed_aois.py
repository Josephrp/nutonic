#!/usr/bin/env python3
"""Write ``*.jsonl`` seed AOIs for ``build_terramind_assessment_sft.py`` from in-repo POI sources.

``build_terramind_assessment_sft.py`` does **not** discover POIs by itself: it only reads
``--seed-aoi`` (JSONL with ``lat``, ``lon``, optional ``analysis_profile``, ``map_id``, ``location_id``)
or a single ``--lat`` / ``--lon``. This exporter connects **common Nutonic POI corpora** to that format.

Sources (``--source``):

* **poi-root** — A GeoGuessr-style download directory (``geoguessr_poi_manifest.json`` or sorted
  ``poi_*/poi.json``), using the same discovery as ``catalog_import_poi.collect_import_jobs``.
* **hf** — Hugging Face rows with coordinates, using the same selection stack as
  ``download_geoguessr_poi_imagery.py`` / ``run_lfm_vl_sft_orchestrator.py`` (``select_hf_points``).
* **events** — A JSON file containing a list of objects with ``event_id``, ``lat``, ``lon``
  (e.g. ``data/events/oceanscout_pois.json`` or ``landshift_pois.json`` from
  ``research_poi_catalog.py``).
* **sat-bbox-sft** — Rows from ``NuTonic/sat-image-boundingbox-sft-full``-style trees: ``data/*.jsonl``
  with ``messages`` referencing ``images/.../poi_*`` or ``mapbox_stills/.../poi_*``. Coordinates come
  from ``metadata/sNNNNN/*.json`` sidecars on Hub (``latitude`` / ``longitude``; ``poi_id`` may be a
  geo-jitter id like ``poi_004613_g004`` — we also register the **base** ``poi_004613`` for seeds),
  from a local ``metadata/`` tree, from ``--poi-latlon-jsonl``, and optionally via
  ``--fetch-metadata-from-hub`` (downloads small JSON files from the dataset repo; no Mapbox calls).

Example::

  python data/scripts/export_terramind_assessment_seed_aois.py poi-root \\
    --poi-root data/downloads/geoguessr_poi_120 --out data/seeds/terramind_from_geoguessr.jsonl

  python data/scripts/export_terramind_assessment_seed_aois.py hf \\
    --num-points 500 --auto-min-separation --max-scan 200000 \\
    --out data/seeds/terramind_hf_pano_500.jsonl

  python data/scripts/export_terramind_assessment_seed_aois.py events \\
    --events-json data/events/oceanscout_pois.json \\
    --default-profile oceanscout_ship_detection \\
    --out data/seeds/terramind_oceanscout_events.jsonl

  python data/scripts/export_terramind_assessment_seed_aois.py sat-bbox-sft \\
    --dataset-root ./path/to/sat-image-boundingbox-sft-full_snapshot \\
    --split train --out data/seeds/terramind_from_sat_bbox.jsonl

  python data/scripts/export_terramind_assessment_seed_aois.py sat-bbox-sft \\
    --hf-repo NuTonic/sat-image-boundingbox-sft-full --split train \\
    --fetch-metadata-from-hub --poi-limit 200 \\
    --out data/seeds/terramind_sat_bbox_hfmeta.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from catalog_import_poi import CatalogImportError, collect_import_jobs
from lfm_vl_sft_dataset.orchestrator_lib import HfSelectionConfig, select_hf_points

# Paths inside ``NuTonic/sat-image-boundingbox-sft-full`` (flat or Hub-sharded ``sNNNNN/``).
_HUB_IMAGE_REL_RE = re.compile(
    r"(images|mapbox_stills)/(s\d{5}/)?(poi_\d+(?:_g\d{3})?(?:_t\d{4})?)\.png\Z",
    re.IGNORECASE,
)


def _base_poi_id_from_image_stem(stem: str) -> str:
    s = stem.strip()
    s = re.sub(r"_t\d{4}\Z", "", s, flags=re.IGNORECASE)
    s = re.sub(r"_g\d{3}\Z", "", s, flags=re.IGNORECASE)
    if re.fullmatch(r"poi_\d+", s):
        return s
    return stem


def _register_poi_latlon_aliases(out: dict[str, tuple[float, float]], pid: str, lat: float, lon: float) -> None:
    """Register ``poi_*`` / geo-jitter ``poi_*_gNNN`` and derived **base** ``poi_<digits>`` for seeds."""
    if not isinstance(pid, str) or not pid.startswith("poi_"):
        return
    pair = (lat, lon)
    out.setdefault(pid, pair)
    base = _base_poi_id_from_image_stem(pid)
    if base != pid:
        out.setdefault(base, pair)


def _parse_hub_image_rel(rel: str) -> tuple[str, str | None, str] | None:
    """Return ``(images|mapbox_stills, shard_or_none, stem_without_ext)``."""
    norm = rel.replace("\\", "/").strip()
    m = _HUB_IMAGE_REL_RE.search(norm)
    if not m:
        return None
    modality, shard_raw, stem = m.group(1), m.group(2), m.group(3)
    shard = shard_raw.rstrip("/") if shard_raw else None
    return modality, shard, stem


def _walk_collect_image_path_parts(obj: Any, acc: list[tuple[str, str | None, str]]) -> None:
    if isinstance(obj, dict):
        if obj.get("type") == "image" and isinstance(obj.get("image"), str):
            parts = _parse_hub_image_rel(obj["image"])
            if parts:
                acc.append(parts)
        for v in obj.values():
            _walk_collect_image_path_parts(v, acc)
    elif isinstance(obj, list):
        for x in obj:
            _walk_collect_image_path_parts(x, acc)


def _pick_best_image_hint(acc: list[tuple[str, str | None, str]]) -> tuple[str, str | None]:
    """Prefer ``images/`` paths (tile stem + shard) over ``mapbox_stills/`` for metadata lookup."""
    if not acc:
        return "", None
    images_only = [x for x in acc if x[0] == "images"]
    pool = images_only if images_only else acc
    _mod, shard, stem = pool[0]
    return stem, shard


def _metadata_json_basenames_for_image_stem(stem: str) -> list[str]:
    """Sidecars use ``<stem>.json``; mapbox-only ``poi_NNN`` chips often pair with ``poi_NNN_t0000.json``."""
    stems = [stem]
    if re.fullmatch(r"poi_\d+", stem, flags=re.IGNORECASE):
        stems.append(f"{stem}_t0000")
    dedup: list[str] = []
    seen: set[str] = set()
    for s in stems:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


def _metadata_rel_candidates(
    image_stem: str,
    shard_hint: str | None,
    *,
    max_shards: int,
) -> list[str]:
    """Ordered Hub-relative paths to try for ``metadata/sNNNNN/<tile>.json`` (see dataset ``metadata/`` layout)."""
    stems = _metadata_json_basenames_for_image_stem(image_stem)
    shard_order: list[str] = []
    seen_sh = set()
    if shard_hint:
        shard_order.append(shard_hint)
        seen_sh.add(shard_hint)
    for i in range(max(0, int(max_shards))):
        sd = f"s{i:05d}"
        if sd not in seen_sh:
            shard_order.append(sd)
            seen_sh.add(sd)
    out: list[str] = []
    seen_rel: set[str] = set()
    for st in stems:
        for sd in shard_order:
            rel = f"metadata/{sd}/{st}.json"
            if rel not in seen_rel:
                seen_rel.add(rel)
                out.append(rel)
    return out


def _index_poi_latlon_from_metadata_dir(dataset_root: Path) -> dict[str, tuple[float, float]]:
    """Index ``metadata/sNNNNN/*.json`` (Hub layout); handles ``poi_id`` with optional ``_gNNN`` jitter suffix."""
    meta_root = dataset_root / "metadata"
    out: dict[str, tuple[float, float]] = {}
    if not meta_root.is_dir():
        return out
    for p in meta_root.rglob("*.json"):
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = o.get("poi_id")
        lat = o.get("latitude")
        lon = o.get("longitude")
        if not isinstance(pid, str):
            continue
        try:
            _register_poi_latlon_aliases(out, pid, float(lat), float(lon))
        except (TypeError, ValueError):
            continue
    return out


def _load_poi_latlon_sidecar_jsonl(path: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        o = json.loads(line)
        pid = str(o.get("poi_id") or "").strip()
        lat = o.get("latitude", o.get("lat"))
        lon = o.get("longitude", o.get("lon"))
        try:
            _register_poi_latlon_aliases(out, pid, float(lat), float(lon))
        except (TypeError, ValueError):
            continue
    return out


def _collect_poi_ids_and_hints_from_sat_bbox_jsonl(
    jsonl_path: Path, *, max_lines: int | None
) -> tuple[list[str], dict[str, tuple[str, str | None]]]:
    """First-seen base POI order plus per-base ``(image_stem, shard)`` hints for metadata JSON lookup."""
    order: dict[str, None] = {}
    hints: dict[str, tuple[str, str | None]] = {}
    n_read = 0
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            if max_lines is not None and n_read >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            n_read += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = row.get("messages")
            if not isinstance(msgs, list):
                continue
            acc: list[tuple[str, str | None, str]] = []
            _walk_collect_image_path_parts(msgs, acc)
            if not acc:
                continue
            by_base: dict[str, list[tuple[str, str | None, str]]] = defaultdict(list)
            for tup in acc:
                stem = tup[2]
                base = _base_poi_id_from_image_stem(stem)
                by_base[base].append(tup)
            for base, lst in by_base.items():
                if base not in order:
                    order[base] = None
                if base not in hints:
                    hints[base] = _pick_best_image_hint(lst)
    return list(order.keys()), hints


def _hub_fetch_metadata_json(repo: str, rel: str, revision: str | None) -> dict[str, Any] | None:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:  # pragma: no cover
        return None
    try:
        p = hf_hub_download(repo, rel, repo_type="dataset", revision=revision)
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _hydrate_latlon_from_hub_metadata(
    *,
    repo: str,
    revision: str | None,
    missing_bases: list[str],
    hints: dict[str, tuple[str, str | None]],
    latlon: dict[str, tuple[float, float]],
    max_shards: int,
    max_downloads: int,
) -> int:
    """Try Hub ``metadata/s*/…json`` for each base POI still missing lat/lon. Returns download attempts."""
    attempts = 0
    for base in missing_bases:
        if base in latlon:
            continue
        stem, shard = hints.get(base, ("", None))
        if not stem:
            continue
        for rel in _metadata_rel_candidates(stem, shard, max_shards=max_shards):
            if attempts >= max_downloads:
                return attempts
            attempts += 1
            o = _hub_fetch_metadata_json(repo, rel, revision)
            if not isinstance(o, dict):
                continue
            pid = o.get("poi_id")
            lat = o.get("latitude")
            lon = o.get("longitude")
            if not isinstance(pid, str):
                continue
            try:
                _register_poi_latlon_aliases(latlon, pid, float(lat), float(lon))
            except (TypeError, ValueError):
                continue
            if base in latlon:
                break
    return attempts


def _resolve_sat_bbox_jsonl_path(ns: argparse.Namespace) -> Path:
    if ns.jsonl is not None:
        return Path(ns.jsonl).resolve()
    repo = (ns.hf_repo or "").strip()
    if repo:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as e:  # pragma: no cover
            raise ImportError("huggingface_hub is required for --hf-repo") from e
        rev_s = str(ns.revision).strip() if ns.revision else None
        p = hf_hub_download(
            repo,
            f"data/{ns.split}.jsonl",
            repo_type="dataset",
            revision=rev_s or None,
        )
        return Path(p).resolve()
    if ns.dataset_root is not None:
        root = Path(ns.dataset_root).resolve()
        return (root / "data" / f"{ns.split}.jsonl").resolve()
    raise ValueError("sat-bbox-sft: provide --jsonl, --hf-repo, or --dataset-root")


def _export_sat_bbox_sft(ns: argparse.Namespace, out: Path) -> int:
    try:
        jsonl_path = _resolve_sat_bbox_jsonl_path(ns)
    except (ImportError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    if not jsonl_path.is_file():
        print(f"Missing JSONL: {jsonl_path}", file=sys.stderr)
        return 2

    poi_ids, hints = _collect_poi_ids_and_hints_from_sat_bbox_jsonl(
        jsonl_path, max_lines=ns.max_jsonl_lines
    )
    if ns.poi_limit is not None:
        poi_ids = poi_ids[: max(0, int(ns.poi_limit))]

    latlon: dict[str, tuple[float, float]] = {}
    if ns.dataset_root is not None:
        latlon.update(_index_poi_latlon_from_metadata_dir(Path(ns.dataset_root).resolve()))
    sidecar = ns.poi_latlon_jsonl
    if sidecar:
        p = Path(sidecar).resolve()
        if not p.is_file():
            print(f"Missing --poi-latlon-jsonl: {p}", file=sys.stderr)
            return 2
        latlon.update(_load_poi_latlon_sidecar_jsonl(p))

    if ns.fetch_metadata_from_hub:
        md_repo = (ns.hf_metadata_repo or ns.hf_repo or "").strip()
        if not md_repo:
            print(
                "--fetch-metadata-from-hub requires --hf-repo or --hf-metadata-repo "
                "(dataset id for metadata/sNNNNN/*.json).",
                file=sys.stderr,
            )
            return 2
        missing_pre = [b for b in poi_ids if b not in latlon]
        rev_s = str(ns.revision).strip() if ns.revision else None
        n_try = _hydrate_latlon_from_hub_metadata(
            repo=md_repo,
            revision=rev_s or None,
            missing_bases=missing_pre,
            hints=hints,
            latlon=latlon,
            max_shards=int(ns.hub_metadata_max_shards),
            max_downloads=int(ns.hub_metadata_max_downloads),
        )
        if n_try:
            still_missing_ct = sum(1 for b in missing_pre if b not in latlon)
            filled_ct = len(missing_pre) - still_missing_ct
            print(
                f"[hub-metadata] download attempts={n_try} against {md_repo!r}; "
                f"filled lat/lon for {filled_ct}/{len(missing_pre)} POI(s) that were missing locally",
                file=sys.stderr,
            )

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for pid in poi_ids:
        pair = latlon.get(pid)
        if pair is None:
            missing.append(pid)
            continue
        lat, lon = pair
        rows.append(
            {
                "lat": lat,
                "lon": lon,
                "analysis_profile": str(ns.default_profile).strip() or "brief_only",
                "map_id": pid,
                "location_id": pid,
            }
        )
    if missing and not ns.skip_missing_latlon:
        preview = ", ".join(missing[:12])
        more = f" (+{len(missing) - 12} more)" if len(missing) > 12 else ""
        print(
            f"No lat/lon for {len(missing)} POI(s) (need metadata/ or --poi-latlon-jsonl): "
            f"{preview}{more}",
            file=sys.stderr,
        )
        return 2
    if missing and ns.skip_missing_latlon:
        print(f"[warn] skipped {len(missing)} POI(s) without lat/lon", file=sys.stderr)
    if not rows:
        print("No seed rows produced (empty POI list or no coordinates).", file=sys.stderr)
        return 2
    _write_jsonl(out.resolve(), rows)
    print(f"Wrote {len(rows)} sat-bbox-sft-derived seed row(s) -> {out.resolve()}")
    return 0


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _seed_from_poi_job(row: dict[str, Any], *, default_profile: str) -> dict[str, Any]:
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    pid = str(row.get("poi_id") or f"poi_{abs(hash((lat, lon))) % 10_000_000_000}")
    prof = str(row.get("analysis_profile") or default_profile).strip() or default_profile
    return {
        "lat": lat,
        "lon": lon,
        "analysis_profile": prof,
        "map_id": pid,
        "location_id": pid,
    }


def _export_poi_root(*, poi_root: Path, out: Path, default_profile: str, poi_limit: int | None) -> int:
    try:
        jobs = collect_import_jobs(poi_root.resolve())
    except CatalogImportError as e:
        print(str(e), file=sys.stderr)
        return 2
    if poi_limit is not None:
        jobs = jobs[: max(0, poi_limit)]
    rows = [_seed_from_poi_job(j, default_profile=default_profile) for j in jobs]
    _write_jsonl(out.resolve(), rows)
    print(f"Wrote {len(rows)} seed row(s) -> {out.resolve()}")
    return 0


def _export_hf(args: argparse.Namespace, out: Path) -> int:
    lat_keys = args.lat_field or ["latitude", "lat", "y"]
    lon_keys = args.lon_field or ["longitude", "lon", "x"]
    cfg = HfSelectionConfig(
        dataset=str(args.dataset),
        dataset_config=args.dataset_config,
        split=str(args.split),
        max_scan=int(args.max_scan),
        streaming=not args.no_streaming,
        lat_keys=lat_keys,
        lon_keys=lon_keys,
        num_points=int(args.num_points),
        min_separation_km=float(args.min_separation_km),
        auto_min_separation=bool(args.auto_min_separation),
        auto_separation_hi_km=float(args.auto_separation_hi_km),
        seed=int(args.seed),
    )
    try:
        points = select_hf_points(cfg)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(points):
        lat = float(p["latitude"])
        lon = float(p["longitude"])
        pid = str(p.get("poi_id") or f"hf_{i:06d}")
        prof = str(p.get("analysis_profile") or args.default_profile).strip() or str(args.default_profile)
        rows.append(
            {
                "lat": lat,
                "lon": lon,
                "analysis_profile": prof,
                "map_id": pid,
                "location_id": pid,
            }
        )
    _write_jsonl(out.resolve(), rows)
    print(f"Wrote {len(rows)} HF-derived seed row(s) -> {out.resolve()}")
    return 0


def _export_events(*, events_json: Path, out: Path, default_profile: str) -> int:
    raw = json.loads(events_json.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("events JSON must be a list of objects", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        eid = str(obj.get("event_id") or obj.get("id") or "").strip()
        if not eid:
            continue
        try:
            lat = float(obj.get("lat"))
            lon = float(obj.get("lon"))
        except (TypeError, ValueError):
            continue
        prof = str(obj.get("analysis_profile") or default_profile).strip() or default_profile
        rows.append(
            {
                "lat": lat,
                "lon": lon,
                "analysis_profile": prof,
                "map_id": eid,
                "location_id": eid,
            }
        )
    _write_jsonl(out.resolve(), rows)
    print(f"Wrote {len(rows)} event-derived seed row(s) -> {out.resolve()}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export TerraMind assessment seed AOI JSONL from POI sources.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="source", required=True)

    p_root = sub.add_parser("poi-root", help="GeoGuessr-style POI tree (manifest or poi_*/poi.json)")
    p_root.add_argument("--poi-root", type=Path, required=True)
    p_root.add_argument("--out", type=Path, required=True)
    p_root.add_argument("--default-profile", default="brief_only")
    p_root.add_argument("--poi-limit", type=int, default=None, help="Cap number of rows after discovery order")

    p_hf = sub.add_parser("hf", help="Hugging Face stochastic / pano pool (same rules as POI downloader)")
    p_hf.add_argument("--out", type=Path, required=True)
    p_hf.add_argument("--default-profile", default="brief_only")
    p_hf.add_argument("--dataset", default="stochastic/random_streetview_images_pano_v0.0.2")
    p_hf.add_argument("--dataset-config", default=None)
    p_hf.add_argument("--split", default="train")
    p_hf.add_argument("--max-scan", type=int, default=100_000)
    p_hf.add_argument("--no-streaming", action="store_true")
    p_hf.add_argument("--lat-field", action="append", default=[])
    p_hf.add_argument("--lon-field", action="append", default=[])
    p_hf.add_argument("--num-points", type=int, default=32)
    p_hf.add_argument("--min-separation-km", type=float, default=2200.0)
    p_hf.add_argument("--auto-min-separation", action="store_true")
    p_hf.add_argument("--auto-separation-hi-km", type=float, default=2200.0)
    p_hf.add_argument("--seed", type=int, default=42)

    p_ev = sub.add_parser("events", help="JSON list with event_id + lat + lon (mini-app event lists)")
    p_ev.add_argument("--events-json", type=Path, required=True)
    p_ev.add_argument("--out", type=Path, required=True)
    p_ev.add_argument("--default-profile", default="brief_only")

    p_sbs = sub.add_parser(
        "sat-bbox-sft",
        help="Seeds from sat-image-boundingbox-sft-full JSONL (messages) + metadata or lat/lon sidecar",
    )
    p_sbs.add_argument("--out", type=Path, required=True)
    p_sbs.add_argument("--default-profile", default="brief_only")
    p_sbs.add_argument("--split", choices=("train", "validation", "test"), default="train")
    p_sbs.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Local dataset folder: data/<split>.jsonl plus optional metadata/ for lat/lon",
    )
    p_sbs.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="Explicit JSONL path (overrides --dataset-root data/<split>.jsonl)",
    )
    p_sbs.add_argument(
        "--hf-repo",
        default="",
        help="Hub repo id (e.g. NuTonic/sat-image-boundingbox-sft-full); loads data/<split>.jsonl from cache",
    )
    p_sbs.add_argument("--revision", default=None, help="Optional Hub git revision (branch / tag / commit)")
    p_sbs.add_argument(
        "--poi-latlon-jsonl",
        type=Path,
        default=None,
        help="JSONL lines {poi_id, latitude, longitude} (or lat/lon); merged over metadata",
    )
    p_sbs.add_argument(
        "--max-jsonl-lines",
        type=int,
        default=None,
        help="Stop scanning after this many non-empty JSON lines (debug / partial scans)",
    )
    p_sbs.add_argument(
        "--poi-limit",
        type=int,
        default=None,
        help="Cap number of distinct POIs in output order after JSONL scan",
    )
    p_sbs.add_argument(
        "--skip-missing-latlon",
        action="store_true",
        help="Drop POIs without coordinates instead of exiting with an error",
    )
    p_sbs.add_argument(
        "--fetch-metadata-from-hub",
        action="store_true",
        help="For POIs still missing lat/lon after local metadata / sidecar, download metadata/*.json "
        "from the Hub dataset repo (requires --hf-metadata-repo or --hf-repo; uses HF cache / token).",
    )
    p_sbs.add_argument(
        "--hf-metadata-repo",
        default="",
        help="Dataset repo id for metadata JSON (default: same as --hf-repo when --fetch-metadata-from-hub is set).",
    )
    p_sbs.add_argument(
        "--hub-metadata-max-shards",
        type=int,
        default=32,
        help="When probing Hub metadata paths, try shard folders s00000 … inclusive of this count minus one.",
    )
    p_sbs.add_argument(
        "--hub-metadata-max-downloads",
        type=int,
        default=50_000,
        help="Safety cap on Hub metadata file download attempts for one exporter run.",
    )

    ns = p.parse_args()
    out = Path(ns.out)

    if ns.source == "poi-root":
        return _export_poi_root(
            poi_root=Path(ns.poi_root),
            out=out,
            default_profile=str(ns.default_profile),
            poi_limit=ns.poi_limit,
        )
    if ns.source == "hf":
        return _export_hf(ns, out)
    if ns.source == "sat-bbox-sft":
        return _export_sat_bbox_sft(ns, out)
    return _export_events(
        events_json=Path(ns.events_json).resolve(),
        out=out,
        default_profile=str(ns.default_profile),
    )


if __name__ == "__main__":
    raise SystemExit(main())
