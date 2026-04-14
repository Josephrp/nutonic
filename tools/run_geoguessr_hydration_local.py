#!/usr/bin/env python3
"""
One-shot local Street View hint hydration: load repo ``.env``, start pano + LFM-VL
services, run ``batch_streetview_hints.py`` for three POIs (two from ``geoguessr_poi_12``,
one from ``geoguessr_poi_120``), then stop the workers.

Requires editable installs::
    pip install -e ./inference/streetview_pano_service -e "./inference/lfm_vl_hint_service[model,dev]"

Does not print values from ``.env``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = REPO_ROOT / "data" / "cache" / "hydration_geoguessr_3" / "catalog"
LOCATIONS = CATALOG_ROOT / "locations"

# Truth coords from ``geoguessr_poi_12/geoguessr_poi_manifest.json`` (first two points)
# and ``geoguessr_poi_120/poi_0067/poi.json``.
POI_ROWS: list[dict[str, Any]] = [
    {"location_id": "poi_0000", "map_id": "poi_0000", "truth_lat": -34.240926, "truth_lon": 138.914068},
    {"location_id": "poi_0001", "map_id": "poi_0001", "truth_lat": 38.6758949, "truth_lon": -27.3289406},
    {"location_id": "poi_0067", "map_id": "poi_0067", "truth_lat": -8.7414001, "truth_lon": 115.5995859},
]


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


def _write_minimal_catalog() -> None:
    LOCATIONS.mkdir(parents=True, exist_ok=True)
    for row in POI_ROWS:
        lid = str(row["location_id"])
        body = (
            f"location_id: {lid}\n"
            f"map_id: {row['map_id']}\n"
            f"truth_lat: {row['truth_lat']}\n"
            f"truth_lon: {row['truth_lon']}\n"
        )
        (LOCATIONS / f"{lid}.yaml").write_text(body, encoding="utf-8")


def _wait_health(url: str, *, label: str, timeout_sec: float, interval_sec: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err: str | None = None
    with httpx.Client(timeout=10.0) as client:
        while time.monotonic() < deadline:
            try:
                r = client.get(url.rstrip("/") + "/health")
                if r.status_code == 200:
                    return
                last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = str(e)
            time.sleep(interval_sec)
    raise RuntimeError(f"{label} health never became OK at {url} (last error: {last_err})")


def main() -> int:
    p = argparse.ArgumentParser(description="Local Google pano + LFM-VL transformers hydration for 3 GeoGuessr POIs.")
    p.add_argument("--pano-port", type=int, default=7861)
    p.add_argument("--lfm-port", type=int, default=7862)
    p.add_argument("--content-version", type=str, default="hydration-geoguessr-3")
    p.add_argument("--frame-count", type=int, default=4)
    p.add_argument("--skip-servers", action="store_true", help="Assume pano/LFM URLs already running; do not spawn.")
    p.add_argument("--pano-service-url", type=str, default=None)
    p.add_argument("--lfm-vl-url", type=str, default=None)
    p.add_argument("--ready-timeout-sec", type=float, default=300.0)
    args = p.parse_args()

    _load_dotenv(REPO_ROOT / ".env")
    if not (os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_STREETVIEW_API_KEY")):
        print("Missing GOOGLE_MAPS_API_KEY (or GOOGLE_STREETVIEW_API_KEY) in environment / .env.", file=sys.stderr)
        return 2

    _write_minimal_catalog()

    pano_url = args.pano_service_url or f"http://127.0.0.1:{args.pano_port}"
    lfm_url = args.lfm_vl_url or f"http://127.0.0.1:{args.lfm_port}"

    pano_proc: subprocess.Popen[str] | None = None
    lfm_proc: subprocess.Popen[str] | None = None
    try:
        if not args.skip_servers:
            pano_src = str(REPO_ROOT / "inference" / "streetview_pano_service" / "src")
            lfm_src = str(REPO_ROOT / "inference" / "lfm_vl_hint_service" / "src")
            pano_env = {
                **os.environ,
                "STREETVIEW_PROVIDER": "google",
                "PYTHONPATH": pano_src
                + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
            }
            lfm_env = {
                **os.environ,
                "LFM_VL_BACKEND": "transformers",
                "PYTHONPATH": lfm_src
                + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
            }
            pano_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "streetview_pano_service.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.pano_port),
                ],
                cwd=str(REPO_ROOT / "inference" / "streetview_pano_service"),
                env=pano_env,
            )
            lfm_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "lfm_vl_hint_service.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.lfm_port),
                ],
                cwd=str(REPO_ROOT / "inference" / "lfm_vl_hint_service"),
                env=lfm_env,
            )

        _wait_health(pano_url, label="pano", timeout_sec=args.ready_timeout_sec)
        _wait_health(lfm_url, label="lfm_vl_hint_service", timeout_sec=args.ready_timeout_sec)

        batch = [
            sys.executable,
            str(REPO_ROOT / "tools" / "batch_streetview_hints.py"),
            "--catalog-root",
            str(CATALOG_ROOT),
            "--pano-service-url",
            pano_url,
            "--lfm-vl-url",
            lfm_url,
            "--content-version",
            args.content_version,
            "--poi-limit",
            "3",
            "--location-ids",
            "poi_0000,poi_0001,poi_0067",
            "--frame-count",
            str(args.frame_count),
            "--lfm-max-frames-per-request",
            str(args.frame_count),
            "--prompt-template-version",
            "transformers-v1",
            "--timeout-sec",
            "600",
        ]
        return int(subprocess.run(batch, cwd=str(REPO_ROOT)).returncode)
    finally:
        for proc in (lfm_proc, pano_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
