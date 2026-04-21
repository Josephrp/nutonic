#!/usr/bin/env python3
"""
End-to-end orchestration for LFM-VL raw SFT: **HF candidate pool -> batched Sentinel/Mapbox
downloads -> geo-jitter -> batched dataset build**, with a **small disk footprint**.

Stages (single command):

1. **Select** geolocated rows from a Hugging Face dataset (same rules as
   ``download_geoguessr_poi_imagery.py``).
2. **Download** POIs in batches of ``--download-batch-size`` into ephemeral
   ``<work-dir>/batch_NNNNN/`` trees (6-digit ``poi_`` ids for global uniqueness).
3. **Geo-jitter** each batch in-place (``--geo-variants`` jitter folders per base POI).
4. **Build** each batch via ``build_lfm_vl_sft_dataset.py`` with ``--stream-jsonl`` and
   ``--prune-sentinel-after-poi`` by default, then **delete** the whole batch directory.

Concurrency:

* **Download parallelism:** ``--download-workers`` runs multiple batches' Sentinel fetches
  at once (higher peak disk - each batch holds full COGs until that batch is processed).
* **Pipeline:** completed batch dirs queue for **``--process-workers``** build threads.
  ``--max-staging-batches`` bounds the queue (back-pressure when builds fall behind).

Remaining flags for the builder (Earth Engine, image-aug, overlays, etc.) are passed
through after ``--``::

  python data/scripts/run_lfm_vl_sft_orchestrator.py \\
    --out-dir data/downloads/lfm_vl_orchestrated \\
    --work-dir data/downloads/lfm_vl_orchestrated_work \\
    --download-batch-size 4 --geo-variants 2 \\
    -- \\
    --ee-project radioshaq --ee-service-account-key path/to.json --no-upload

Prerequisites: same as ``download_geoguessr_poi_imagery`` + ``build_lfm_vl_sft_dataset``
(``pip install -r data/scripts/requirements.txt -r data/scripts/requirements-lfm-vl-dataset.txt``).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import threading

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from download_geoguessr_poi_imagery import _load_simsat_module
from lfm_vl_sft_dataset.ee_auth import initialize_earth_engine
from lfm_vl_sft_dataset.jsonl_format import truncate_split_jsonl_files
from lfm_vl_sft_dataset.orchestrator_lib import (
    BatchDownloadConfig,
    HfSelectionConfig,
    apply_geo_jitter_under_root,
    iter_batch_slices,
    materialize_batch,
    rm_tree_quiet,
    select_hf_points,
)

_BUILD = _SCRIPTS / "build_lfm_vl_sft_dataset.py"
_POISON = object()


def _build_cmd(
    batch_dir: Path,
    out_dir: Path,
    *,
    stream_jsonl: bool,
    stream_skip_truncate: bool,
    prune_sentinel: bool,
    prune_mapbox: bool,
    prune_allow_external: bool,
    build_rest: list[str],
) -> list[str]:
    cmd = [
        sys.executable,
        str(_BUILD),
        "--poi-root",
        str(batch_dir),
        "--out-dir",
        str(out_dir),
    ]
    if stream_jsonl:
        cmd.append("--stream-jsonl")
        if stream_skip_truncate:
            cmd.append("--stream-jsonl-skip-init-truncate")
    if prune_sentinel:
        cmd.append("--prune-sentinel-after-poi")
    if prune_mapbox:
        cmd.append("--prune-poi-mapbox-after-poi")
    if prune_allow_external:
        cmd.append("--prune-allow-external")
    cmd.extend(build_rest)
    return cmd


def main() -> int:
    p = argparse.ArgumentParser(
        description="Orchestrate HF -> batched download + geo-jitter + LFM-VL dataset build with bounded disk.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Output / work
    p.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Final dataset root (images/, data/, metadata/, ...) passed to each batch build.",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Ephemeral batch trees (default: <out-dir>_work next to out-dir). Removed after each batch.",
    )
    p.add_argument(
        "--clean-work-dir",
        action="store_true",
        help="Delete --work-dir at startup (recommended for a fresh run).",
    )
    # HF + selection
    p.add_argument("--dataset", default="stochastic/random_streetview_images_pano_v0.0.2")
    p.add_argument("--dataset-config", default=None)
    p.add_argument("--split", default="train")
    p.add_argument("--max-scan", type=int, default=100_000)
    p.add_argument("--no-streaming", action="store_true", help="HF load_dataset(..., streaming=False).")
    p.add_argument("--lat-field", action="append", default=[], help="Latitude column (repeatable).")
    p.add_argument("--lon-field", action="append", default=[], help="Longitude column (repeatable).")
    p.add_argument(
        "--num-points",
        type=int,
        default=12,
        help="POI count after selection (0 = entire geolocated pool under --max-scan).",
    )
    p.add_argument("--min-separation-km", type=float, default=2200.0)
    p.add_argument("--auto-min-separation", action="store_true")
    p.add_argument("--auto-separation-hi-km", type=float, default=2200.0)
    p.add_argument("--seed", type=int, default=42)
    # Download / STAC / Mapbox
    p.add_argument("--bbox-km", type=float, default=5.0)
    p.add_argument("--datetime-days", type=int, default=90)
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument("--max-cloud-cover", type=float, default=100.0)
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--sentinel-mode", choices=("minimal", "full"), default="full")
    p.add_argument("--no-mapbox", action="store_true")
    p.add_argument("--mapbox-zoom", type=float, default=12.0)
    p.add_argument("--mapbox-size", type=int, default=1280)
    # Batching + concurrency
    p.add_argument("--download-batch-size", type=int, default=8, help="POIs per ephemeral batch directory.")
    p.add_argument(
        "--download-workers",
        type=int,
        default=1,
        help="Parallel batch downloads (each batch retains Sentinel COGs until built).",
    )
    p.add_argument(
        "--process-workers",
        type=int,
        default=1,
        help="Parallel build subprocesses consuming completed batch dirs from the staging queue.",
    )
    p.add_argument(
        "--max-staging-batches",
        type=int,
        default=2,
        help="Max completed batch dirs waiting for build (download blocks when full).",
    )
    # Geo-jitter
    p.add_argument("--geo-variants", type=int, default=2)
    p.add_argument("--geo-max-offset-m", type=float, default=300.0)
    p.add_argument("--jitter-seed", type=int, default=42, help="RNG base for geo-jitter (per base POI).")
    # Build defaults for disk
    p.add_argument(
        "--no-stream-jsonl",
        action="store_true",
        help="Disable streamed JSONL (not recommended for large runs; buffers rows per batch).",
    )
    p.add_argument("--no-prune-sentinel", action="store_true", help="Keep sentinel-2-l2a/ after each POI (large disk).")
    p.add_argument("--prune-poi-mapbox-after-poi", action="store_true")
    p.add_argument("--prune-allow-external", action="store_true")
    # Earth Engine (optional if build uses synthetic)
    p.add_argument("--synthetic-labels", action="store_true", help="Forwarded to build (skip EE).")
    p.add_argument("--ee-project", default=None)
    p.add_argument("--ee-service-account-key", type=Path, default=None)
    p.add_argument("--ee-service-account-email", default=None)
    p.add_argument(
        "--hf-token",
        default=None,
        help="If set, passed to each build subprocess as --hf-token (Hub upload; overrides env for that process).",
    )

    args, build_rest = p.parse_known_args()

    out_dir = args.out_dir.resolve()
    work_dir = (args.work_dir or (out_dir.parent / f"{out_dir.name}_work")).resolve()
    if args.clean_work_dir:
        rm_tree_quiet(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    lat_keys = args.lat_field or ["latitude", "lat", "y"]
    lon_keys = args.lon_field or ["longitude", "lon", "x"]

    hf_cfg = HfSelectionConfig(
        dataset=args.dataset,
        dataset_config=args.dataset_config,
        split=args.split,
        max_scan=args.max_scan,
        streaming=not args.no_streaming,
        lat_keys=lat_keys,
        lon_keys=lon_keys,
        num_points=args.num_points,
        min_separation_km=args.min_separation_km,
        auto_min_separation=args.auto_min_separation,
        auto_separation_hi_km=args.auto_separation_hi_km,
        seed=args.seed,
    )
    print("Selecting HF POIs...", flush=True)
    try:
        points = select_hf_points(hf_cfg)
    except Exception as e:  # noqa: BLE001
        print(f"HF selection failed: {e}", file=sys.stderr)
        return 2
    print(f"Selected {len(points)} POI(s); batch size {args.download_batch_size}", flush=True)

    dl = BatchDownloadConfig(
        stac_url=args.stac_url,
        collection=args.collection,
        datetime_days=args.datetime_days,
        bbox_km=args.bbox_km,
        max_cloud_cover=args.max_cloud_cover,
        skip_existing=args.skip_existing,
        sentinel_mode=args.sentinel_mode,
        no_mapbox=args.no_mapbox,
        mapbox_zoom=args.mapbox_zoom,
        mapbox_size=args.mapbox_size,
        hf_dataset=args.dataset,
        hf_split=args.split,
    )

    stream_jsonl = not args.no_stream_jsonl
    prune_sentinel = not args.no_prune_sentinel
    if stream_jsonl:
        truncate_split_jsonl_files(out_dir / "data")
        print("Truncated split JSONLs once under out-dir/data/ (orchestrator multi-batch mode).", flush=True)

    if not args.synthetic_labels:
        try:
            info = initialize_earth_engine(
                project=args.ee_project,
                service_account_key=args.ee_service_account_key,
                service_account_email=args.ee_service_account_email,
            )
            print(f"Earth Engine: {info}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"Earth Engine init failed: {e}", file=sys.stderr)
            return 2

    simsat = _load_simsat_module()
    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-lfm-vl-orchestrator/1.0"})

    batch_tasks = list(iter_batch_slices(points, args.download_batch_size))
    staging: Queue = Queue(maxsize=max(1, args.max_staging_batches))
    errors: list[str] = []
    err_lock = threading.Lock()

    def do_one_batch(task: tuple[int, int, list]) -> Path:
        bid, gstart, sl = task
        bdir = work_dir / f"batch_{bid:05d}"
        rm_tree_quiet(bdir)
        for n in materialize_batch(simsat, session, bdir, sl, gstart, dl):
            print(n, flush=True)
        notes = apply_geo_jitter_under_root(
            simsat,
            session,
            bdir,
            geo_variants=max(0, args.geo_variants),
            geo_max_offset_m=args.geo_max_offset_m,
            jitter_seed=args.jitter_seed,
            dl=dl,
        )
        for n in notes:
            print(n, flush=True)
        return bdir

    def producer() -> None:
        try:
            with ThreadPoolExecutor(max_workers=max(1, args.download_workers)) as ex:
                futs = [ex.submit(do_one_batch, t) for t in batch_tasks]
                for fut in as_completed(futs):
                    try:
                        bdir = fut.result()
                        staging.put(bdir)
                    except Exception as e:  # noqa: BLE001
                        with err_lock:
                            errors.append(str(e))
        finally:
            for _ in range(max(1, args.process_workers)):
                staging.put(_POISON)

    def consumer() -> None:
        while True:
            bdir = staging.get()
            if bdir is _POISON:
                return
            cmd = _build_cmd(
                bdir,
                out_dir,
                stream_jsonl=stream_jsonl,
                stream_skip_truncate=stream_jsonl,
                prune_sentinel=prune_sentinel,
                prune_mapbox=args.prune_poi_mapbox_after_poi,
                prune_allow_external=args.prune_allow_external,
                build_rest=build_rest,
            )
            if args.synthetic_labels:
                cmd.append("--synthetic-labels")
            if args.ee_project:
                cmd.extend(["--ee-project", args.ee_project])
            if args.ee_service_account_key:
                cmd.extend(["--ee-service-account-key", str(args.ee_service_account_key)])
            if args.ee_service_account_email:
                cmd.extend(["--ee-service-account-email", args.ee_service_account_email])
            if args.hf_token:
                cmd.extend(["--hf-token", args.hf_token])
            r = subprocess.run(cmd, cwd=str(REPO_ROOT))
            if r.returncode != 0:
                with err_lock:
                    errors.append(f"build failed for {bdir.name} rc={r.returncode}")
            rm_tree_quiet(bdir)

    prod = threading.Thread(target=producer, name="orchestrator-download", daemon=True)
    prod.start()
    consumers = [
        threading.Thread(target=consumer, name=f"orchestrator-build-{i}", daemon=True)
        for i in range(max(1, args.process_workers))
    ]
    for c in consumers:
        c.start()
    prod.join()
    for c in consumers:
        c.join()

    spec = importlib.util.spec_from_file_location("build_lfm_vl_sft_dataset", _BUILD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {_BUILD}")
    bmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmod)
    (out_dir / "README.md").write_text(bmod.DATASET_README, encoding="utf-8")

    if errors:
        print("Orchestrator errors:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"Done. Dataset under {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())