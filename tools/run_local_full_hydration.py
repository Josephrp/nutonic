#!/usr/bin/env python3
"""
**DEV ONLY:** runs the shipped-cache prep pipeline + Street View / LFM-VL **on this machine**
(starts ``uvicorn`` for pano + LFM-VL, which **loads Transformers weights locally**).

**Production / default workflow:** use Hugging Face Jobs instead (no local weight load)::

    python tools/run_full_hydration.py --content-version ... --sv-image ... [--llm-image ...]

Uses an isolated catalog under ``data/cache/<content-version>/catalog``. Requires
``--allow-local-model-weights`` (or ``NUTONIC_ALLOW_LOCAL_LFM_WEIGHTS=1``) or this script exits.

Editable installs::

    pip install -e ./inference/streetview_pano_service -e "./inference/lfm_vl_hint_service[model,dev]"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


def _run(py: str, argv: list[str], *, cwd: Path | None = None) -> None:
    cmd = [py, *argv]
    print("+", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=False).returncode
    if rc != 0:
        raise SystemExit(rc)


def _wait_health(url: str, *, label: str, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err: str | None = None
    base = url.rstrip("/") + "/health"
    with httpx.Client(timeout=15.0) as client:
        while time.monotonic() < deadline:
            try:
                r = client.get(base)
                if r.status_code == 200:
                    return
                last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = str(e)
            time.sleep(1.5)
    raise RuntimeError(f"{label} health never OK at {base} (last: {last_err})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="DEV ONLY: local full hydration (loads LFM weights on this machine). Prefer tools/run_full_hydration.py for HF Jobs.",
    )
    p.add_argument(
        "--allow-local-model-weights",
        action="store_true",
        help="Required to run; acknowledges that LFM-VL runs locally (not on Hugging Face Jobs).",
    )
    p.add_argument("--content-version", type=str, default="hydration-local-5poi")
    p.add_argument("--poi-limit", type=int, default=5)
    p.add_argument(
        "--location-ids",
        type=str,
        default=None,
        help="Comma-separated poi_* ids; if set, copies only those folders into a temp POI root (avoids bad rows in the first N by sorted order).",
    )
    p.add_argument(
        "--poi-root",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12",
        help="Single POI tree root (layout A or B).",
    )
    p.add_argument("--pano-port", type=int, default=7861)
    p.add_argument("--lfm-port", type=int, default=7862)
    p.add_argument("--frame-count", type=int, default=4)
    p.add_argument("--ready-timeout-sec", type=float, default=900.0)
    p.add_argument("--batch-timeout-sec", type=float, default=900.0)
    p.add_argument("--skip-servers", action="store_true")
    p.add_argument("--pano-service-url", type=str, default=None)
    p.add_argument("--lfm-vl-url", type=str, default=None)
    p.add_argument("--skip-narrative", action="store_true")
    p.add_argument(
        "--skip-geo-hints",
        action="store_true",
        help="Skip build_poi_geo_context + compile_useful_hint_tiers (use when Natural Earth geometry fails for some POIs). Still runs Mapbox stills + batch.",
    )
    args = p.parse_args(argv)

    if not args.allow_local_model_weights and os.environ.get("NUTONIC_ALLOW_LOCAL_LFM_WEIGHTS") != "1":
        print(
            "This script would start local LFM-VL (Transformers) and load model weights on this machine.\n"
            "For full hydration on Hugging Face Jobs (recommended), run:\n"
            "  python tools/run_full_hydration.py --content-version YOUR_CV --sv-image YOUR_DOCKER_IMAGE [...]\n"
            "To force local dev anyway, pass --allow-local-model-weights or set NUTONIC_ALLOW_LOCAL_LFM_WEIGHTS=1.",
            file=sys.stderr,
        )
        return 2

    _load_dotenv(REPO_ROOT / ".env")
    if not (os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_STREETVIEW_API_KEY")):
        print("Missing GOOGLE_MAPS_API_KEY (or GOOGLE_STREETVIEW_API_KEY).", file=sys.stderr)
        return 2
    if not (os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_TOKEN")):
        print("Missing MAPBOX_ACCESS_TOKEN (or MAPBOX_TOKEN).", file=sys.stderr)
        return 2

    cv = args.content_version
    py = sys.executable
    poi_root = args.poi_root.resolve()
    if not poi_root.is_dir():
        print(f"POI root not found: {poi_root}", file=sys.stderr)
        return 2

    catalog_root = REPO_ROOT / "data" / "cache" / cv / "catalog"
    catalog_root.mkdir(parents=True, exist_ok=True)
    os.environ["NUTONIC_CONTENT_VERSION"] = cv

    import_root = poi_root
    import_argv_tail: list[str]
    n_pois = args.poi_limit
    if args.location_ids:
        lids = [x.strip() for x in args.location_ids.split(",") if x.strip()]
        if not lids:
            print("--location-ids was empty", file=sys.stderr)
            return 2
        n_pois = len(lids)
        slice_root = REPO_ROOT / "data" / "cache" / cv / "_poi_import_slice"
        if slice_root.exists():
            shutil.rmtree(slice_root)
        slice_root.mkdir(parents=True)
        for lid in lids:
            src = poi_root / lid
            if not (src / "poi.json").is_file():
                print(f"Missing {src / 'poi.json'}", file=sys.stderr)
                return 2
            shutil.copytree(src, slice_root / lid)
        import_root = slice_root
        import_argv_tail = []
    else:
        import_argv_tail = ["--poi-limit", str(args.poi_limit)]

    _run(
        py,
        [
            str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
            "--poi-root",
            str(import_root),
            "--catalog-root",
            str(catalog_root),
            "--content-version",
            cv,
            "--ranked-split",
            "half",
            *import_argv_tail,
        ],
    )
    _run(py, [str(REPO_ROOT / "data" / "scripts" / "catalog_lint.py"), "--catalog-root", str(catalog_root)])
    _run(py, [str(REPO_ROOT / "data" / "scripts" / "fetch_geo_baselines.py")])
    hints_dir = REPO_ROOT / "data" / "cache" / cv / "useful_hints"
    if not args.skip_geo_hints:
        _run(
            py,
            [
                str(REPO_ROOT / "data" / "scripts" / "build_poi_geo_context.py"),
                "--catalog-root",
                str(catalog_root),
                "--content-version",
                cv,
            ],
        )
        geo_dir = REPO_ROOT / "data" / "cache" / cv / "geo_context"
        _run(
            py,
            [
                str(REPO_ROOT / "data" / "scripts" / "compile_useful_hint_tiers.py"),
                "--content-version",
                cv,
                "--geo-context-dir",
                str(geo_dir),
                "--output-dir",
                str(hints_dir),
            ],
        )
    still_meta = REPO_ROOT / "data" / "cache" / cv / "build_stills"
    _run(
        py,
        [
            str(REPO_ROOT / "data" / "scripts" / "render_mapbox_still.py"),
            "--catalog-root",
            str(catalog_root),
            "--meta-dir",
            str(still_meta),
            "--allow-network",
        ],
    )

    if not args.skip_narrative:
        out_narr = REPO_ROOT / "data" / "cache" / cv / "narrative"
        _run(
            py,
            [
                str(REPO_ROOT / "data" / "scripts" / "narrative_llm_batch.py"),
                "--content-version",
                cv,
                "--catalog-root",
                str(catalog_root),
                "--output-dir",
                str(out_narr),
            ],
        )

    pano_url = args.pano_service_url or f"http://127.0.0.1:{args.pano_port}"
    lfm_url = args.lfm_vl_url or f"http://127.0.0.1:{args.lfm_port}"
    pano_proc: subprocess.Popen[str] | None = None
    lfm_proc: subprocess.Popen[str] | None = None
    try:
        if not args.skip_servers:
            pano_cwd = REPO_ROOT / "inference" / "streetview_pano_service"
            lfm_cwd = REPO_ROOT / "inference" / "lfm_vl_hint_service"
            pano_src = pano_cwd / "src"
            lfm_src = lfm_cwd / "src"
            pano_env = {
                **os.environ,
                "STREETVIEW_PROVIDER": "google",
                "PYTHONPATH": str(pano_src)
                + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
            }
            lfm_env = {
                **os.environ,
                "LFM_VL_BACKEND": "transformers",
                "PYTHONPATH": str(lfm_src)
                + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
            }
            pano_proc = subprocess.Popen(
                [
                    py,
                    "-m",
                    "uvicorn",
                    "streetview_pano_service.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.pano_port),
                ],
                cwd=str(pano_cwd),
                env=pano_env,
            )
            lfm_proc = subprocess.Popen(
                [
                    py,
                    "-m",
                    "uvicorn",
                    "lfm_vl_hint_service.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.lfm_port),
                ],
                cwd=str(lfm_cwd),
                env=lfm_env,
            )

        _wait_health(pano_url, label="pano", timeout_sec=args.ready_timeout_sec)
        _wait_health(lfm_url, label="lfm_vl_hint_service", timeout_sec=args.ready_timeout_sec)

        still_index = still_meta / "still_index.json"
        batch = [
            py,
            str(REPO_ROOT / "tools" / "batch_streetview_hints.py"),
            "--catalog-root",
            str(catalog_root),
            "--pano-service-url",
            pano_url,
            "--lfm-vl-url",
            lfm_url,
            "--content-version",
            cv,
            "--poi-limit",
            str(n_pois),
            "--still-index",
            str(still_index),
            "--frame-count",
            str(args.frame_count),
            "--lfm-max-frames-per-request",
            str(args.frame_count),
            "--prompt-template-version",
            "transformers-v1",
            "--timeout-sec",
            str(args.batch_timeout_sec),
            "--allow-partial",
        ]
        if not args.skip_geo_hints:
            pos = batch.index("--frame-count")
            batch.insert(pos, str(hints_dir))
            batch.insert(pos, "--useful-hints-dir")
        rc = subprocess.run(batch, cwd=str(REPO_ROOT)).returncode
        return int(rc)
    finally:
        for proc in (lfm_proc, pano_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
