#!/usr/bin/env python3
"""
Download all Sentinel-2 L2A STAC assets and optional Mapbox satellite static imagery.

Mirrors the client data sources used in refs/SimSat-main:
  - STAC: https://earth-search.aws.element84.com/v1, collection sentinel-2-l2a
  - Mapbox: https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/...
    (requires MAPBOX_ACCESS_TOKEN)

Sentinel-2 assets include every layer exposed on each item (COG GeoTIFF, JP2000
duplicates, thumbnail, metadata, etc.). Global downloads are not supported: you
must pass a bbox, datetime window, and sensible --max-items.

Usage (from repo root):
  pip install -r data/scripts/requirements.txt
  python data/scripts/download_simsat_sources.py --out-dir data/downloads
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from pystac_client import Client

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION_ID = "sentinel-2-l2a"
MAPBOX_STYLE = "mapbox/satellite-v9"


def _suffix_for_asset(media_type: str | None, href: str) -> str:
    if media_type:
        mt = media_type.split(";")[0].strip().lower()
        if "geotiff" in mt or mt == "image/tiff":
            return ".tif"
        if "jp2" in mt or mt == "image/jp2":
            return ".jp2"
        if "jpeg" in mt or mt == "image/jpeg":
            return ".jpg"
        if "xml" in mt:
            return ".xml"
        if "json" in mt:
            return ".json"
    path = urlparse(href).path
    for ext in (".tif", ".tiff", ".jp2", ".jpg", ".jpeg", ".xml", ".json", ".png"):
        if path.lower().endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"
    return ""


def _safe_filename(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "asset"


def resolve_href(href: str) -> str:
    """Earth Search often lists JP2 and some auxiliary assets as s3:// URIs; use HTTPS to the public dataset."""
    if not href.startswith("s3://"):
        return href
    _, rest = href.split("s3://", 1)
    bucket, _, key = rest.partition("/")
    if bucket == "sentinel-s2-l2a":
        return f"https://sentinel-s2-l2a.s3.eu-central-1.amazonaws.com/{key}"
    if bucket == "sentinel-s2-l1c":
        return f"https://sentinel-s2-l1c.s3.eu-central-1.amazonaws.com/{key}"
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def download_url(
    session: requests.Session,
    url: str,
    dest: Path,
    chunk_size: int = 1024 * 1024,
    timeout: int = 600,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
    tmp.replace(dest)


def download_sentinel_item_assets(
    session: requests.Session,
    item,
    item_dir: Path,
    skip_existing: bool,
    optional_asset_keys: frozenset[str],
) -> tuple[list[str], list[str]]:
    """Returns (hard_errors, soft_warnings). Soft = optional asset missing (e.g. 404)."""
    errors: list[str] = []
    warnings: list[str] = []
    for key, asset in item.assets.items():
        suffix = _suffix_for_asset(asset.media_type, asset.href)
        filename = _safe_filename(key) + suffix
        dest = item_dir / filename
        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            download_url(session, resolve_href(asset.href), dest)
        except requests.HTTPError as e:
            msg = f"{item.id}/{key}: {e}"
            if (
                key in optional_asset_keys
                and e.response is not None
                and e.response.status_code == 404
            ):
                warnings.append(msg)
            else:
                errors.append(msg)
        except Exception as e:  # noqa: BLE001 — surface per-asset failures
            errors.append(f"{item.id}/{key}: {e}")
    return errors, warnings


def fetch_mapbox_static(
    session: requests.Session,
    token: str,
    lon: float,
    lat: float,
    zoom: float,
    bearing: float,
    pitch: float,
    width: int,
    height: int,
    retina: bool,
    dest: Path,
) -> None:
    """Same URL shape as refs/SimSat-main mapbox_provider.py."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    wh = f"{width}x{height}"
    if retina:
        wh += "@2x"
    url = (
        f"https://api.mapbox.com/styles/v1/{MAPBOX_STYLE}/static/"
        f"{lon},{lat},{zoom},{bearing},{pitch}/{wh}"
        f"?access_token={token}"
    )
    download_url(session, url, dest, timeout=120)


def main() -> int:
    p = argparse.ArgumentParser(description="Download SimSat-style Sentinel-2 + Mapbox sources.")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/downloads"),
        help="Root output directory (default: data/downloads)",
    )
    p.add_argument("--stac-url", default=STAC_URL)
    p.add_argument("--collection", default=COLLECTION_ID)
    p.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=(6.55, 46.50, 6.70, 46.56),
        help="WGS84 bbox (default: ~Lausanne CH, as in SimSat samples)",
    )
    p.add_argument(
        "--datetime",
        default=None,
        help='STAC datetime interval, e.g. "2024-06-01/2024-06-15" (default: last 60 days)',
    )
    p.add_argument("--max-cloud-cover", type=float, default=100.0)
    p.add_argument("--max-items", type=int, default=1, help="Cap STAC items (each has many GB of assets).")
    p.add_argument("--skip-existing", action="store_true", help="Resume partial downloads.")
    p.add_argument("--no-mapbox", action="store_true", help="Skip Mapbox even if token is set.")
    p.add_argument("--mapbox-zoom", type=float, default=12.0)
    p.add_argument("--mapbox-bearing", type=float, default=0.0)
    p.add_argument("--mapbox-pitch", type=float, default=0.0)
    p.add_argument("--mapbox-size", type=int, default=1280, help="Width and height in px.")
    p.add_argument("--dry-run", action="store_true", help="List items and assets only.")
    p.add_argument(
        "--optional-assets",
        nargs="*",
        default=["product_metadata"],
        help="Asset keys for which HTTP 404 is recorded as warning only (default: product_metadata).",
    )
    args = p.parse_args()

    out: Path = args.out_dir.resolve()
    s2_root = out / "sentinel-2-l2a"
    meta_path = out / "run_manifest.json"

    west, south, east, north = args.bbox
    if args.datetime:
        dt = args.datetime
    else:
        # Rolling window so a default run usually finds data.
        end = time.time()
        start = end - 60 * 24 * 3600
        dt = f"{time.strftime('%Y-%m-%d', time.gmtime(start))}/{time.strftime('%Y-%m-%d', time.gmtime(end))}"

    client = Client.open(args.stac_url)
    search = client.search(
        collections=[args.collection],
        bbox=[west, south, east, north],
        datetime=dt,
        max_items=args.max_items,
        query={"eo:cloud_cover": {"lt": args.max_cloud_cover}},
    )
    items = list(search.items())
    if not items:
        print("No STAC items matched. Widen --bbox, adjust --datetime, or raise --max-cloud-cover.", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Would process {len(items)} item(s) into {s2_root}")
        for it in items:
            print(f"  {it.id}  assets={list(it.assets.keys())}")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-download-simsat-sources/1.0"})

    optional_keys = frozenset(args.optional_assets)
    all_errors: list[str] = []
    all_warnings: list[str] = []
    for it in items:
        item_dir = s2_root / _safe_filename(it.id)
        errs, warns = download_sentinel_item_assets(
            session, it, item_dir, skip_existing=args.skip_existing, optional_asset_keys=optional_keys
        )
        all_errors.extend(errs)
        all_warnings.extend(warns)

    mapbox_info = None
    token = os.environ.get("MAPBOX_ACCESS_TOKEN")
    if not args.no_mapbox and token:
        clon = (west + east) / 2.0
        clat = (south + north) / 2.0
        mb_path = out / "mapbox" / f"satellite-v9_{clon:.5f}_{clat:.5f}_z{args.mapbox_zoom}.png"
        if args.skip_existing and mb_path.exists() and mb_path.stat().st_size > 0:
            mapbox_info = {"path": str(mb_path), "skipped": True}
        else:
            try:
                fetch_mapbox_static(
                    session,
                    token,
                    clon,
                    clat,
                    args.mapbox_zoom,
                    args.mapbox_bearing,
                    args.mapbox_pitch,
                    args.mapbox_size,
                    args.mapbox_size,
                    True,
                    mb_path,
                )
                mapbox_info = {"path": str(mb_path), "skipped": False}
            except Exception as e:  # noqa: BLE001
                mapbox_info = {"error": str(e)}
                all_errors.append(f"mapbox: {e}")
    elif not args.no_mapbox:
        mapbox_info = {"skipped": True, "reason": "MAPBOX_ACCESS_TOKEN not set"}

    manifest = {
        "stac_url": args.stac_url,
        "collection": args.collection,
        "bbox": [west, south, east, north],
        "datetime": dt,
        "items": [it.id for it in items],
        "output": str(out),
        "mapbox": mapbox_info,
        "errors": all_errors,
        "warnings": all_warnings,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if all_warnings:
        print("Warnings:", file=sys.stderr)
        for w in all_warnings:
            print(f"  {w}", file=sys.stderr)
    if all_errors:
        print("Completed with errors:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"Wrote Sentinel assets under {s2_root}")
    if mapbox_info:
        print(f"Mapbox: {mapbox_info}")
    print(f"Manifest: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
