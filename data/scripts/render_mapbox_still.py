#!/usr/bin/env python3
"""
Render or reuse Mapbox-style reference stills for catalog locations.

Normative: docs/scripts/SPEC-render-mapbox-still.md
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml
from PIL import Image, ImageOps

# CLI runs from repo root: ensure flat imports match pytest (conftest).
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    if os.environ.get("NUTONIC_NO_DOTENV") != "1":
        load_dotenv(REPO_ROOT / ".env")
        load_dotenv()
except ImportError:
    pass

EXIT_MISSING_TOKEN = 4
EXIT_MAPBOX_HTTP = 5
EXIT_INPUT = 2


class RenderMapboxStillError(Exception):
    """Domain error with stable exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StillPolicy:
    width_px: int = 1280
    height_px: int = 1280
    zoom: float = 12.0
    style_id: str = "satellite-v9"
    max_edge_px: int = 1536


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RenderMapboxStillError(f"{path}: expected YAML mapping at root", 2)
    return raw


def load_still_policy_file(path: Path | None) -> StillPolicy:
    if path is None:
        return StillPolicy()
    data = _load_yaml_mapping(path)
    return StillPolicy(
        width_px=int(data.get("width_px", 1280)),
        height_px=int(data.get("height_px", 1280)),
        zoom=float(data.get("zoom", 12.0)),
        style_id=str(data.get("style_id", "satellite-v9")),
        max_edge_px=int(data.get("max_edge_px", 1536)),
    )


def _merge_policy(base: StillPolicy, render_policy: dict[str, Any] | None) -> StillPolicy:
    if not render_policy:
        return base
    return StillPolicy(
        width_px=int(render_policy.get("width_px", base.width_px)),
        height_px=int(render_policy.get("height_px", base.height_px)),
        zoom=float(render_policy.get("zoom", base.zoom)),
        style_id=str(render_policy.get("style", render_policy.get("style_id", base.style_id))),
        max_edge_px=int(render_policy.get("max_edge_px", base.max_edge_px)),
    )


def _list_location_files(catalog_root: Path) -> list[Path]:
    loc_dir = catalog_root / "locations"
    if not loc_dir.is_dir():
        return []
    return sorted(loc_dir.glob("*.yaml"))


def _jpeg_bytes(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=quality, optimize=True, progressive=False)
    return buf.getvalue()


def _fit_within_max_edge(img: Image.Image, max_edge: int) -> tuple[Image.Image, bool]:
    w, h = img.size
    edge = max(w, h)
    if edge <= max_edge:
        return img, False
    scale = max_edge / float(edge)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return img.resize((nw, nh), Image.Resampling.LANCZOS), True


def _contain_to_policy_box(img: Image.Image, policy: StillPolicy) -> tuple[Image.Image, bool]:
    """Resize with aspect preserved to fit inside policy width/height; never upscale."""
    target = (policy.width_px, policy.height_px)
    before = img.size
    out = ImageOps.contain(img, target)
    return out, out.size != before


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mapbox_access_token() -> str | None:
    return (os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_TOKEN") or "").strip() or None


def _fetch_mapbox_static_image(
    lon: float,
    lat: float,
    zoom: float,
    width: int,
    height: int,
    style_id: str,
    token: str,
) -> bytes:
    # https://docs.mapbox.com/api/maps/static-images/
    url = f"https://api.mapbox.com/styles/v1/mapbox/{style_id}/static/{lon:f},{lat:f},{zoom:f},0,0/{width}x{height}"
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, params={"access_token": token}, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
            raise RenderMapboxStillError(
                f"Mapbox static HTTP {r.status_code}: {r.text[:200]!r}",
                EXIT_MAPBOX_HTTP,
            )
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
    raise RenderMapboxStillError(f"Mapbox static request failed: {last_err}", EXIT_MAPBOX_HTTP)


def _load_image_from_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def process_location(
    location_id: str,
    map_id: str,
    truth_lat: float,
    truth_lon: float,
    still_source: dict[str, Any] | None,
    policy: StillPolicy,
    *,
    repo_root: Path,
    compose_maps_dir: Path,
    meta_stills_dir: Path,
    reuse_only: bool,
    allow_network: bool,
    dry_run: bool,
) -> dict[str, Any]:
    bundled = (still_source or {}).get("bundled_relative")
    render_policy = (still_source or {}).get("render_policy")
    effective = _merge_policy(policy, render_policy if isinstance(render_policy, dict) else None)

    rel_out = f"files/maps/{location_id}.jpg"
    dest_path = compose_maps_dir / f"{location_id}.jpg"
    meta_path = meta_stills_dir / f"{location_id}.meta.json"
    cache_jpeg_path = meta_stills_dir / f"{location_id}.jpg"

    center_lat = truth_lat
    center_lon = truth_lon
    if isinstance(render_policy, dict):
        center_lat = float(render_policy.get("center_lat", center_lat))
        center_lon = float(render_policy.get("center_lon", center_lon))

    img: Image.Image | None = None
    policy_mismatch = False
    source_label = ""

    if bundled:
        src = repo_root / str(bundled)
        if not src.is_file():
            raise RenderMapboxStillError(f"Missing bundled still for {location_id}: {src}", EXIT_INPUT)
        img = Image.open(src)
        source_label = "bundled_relative"
        ow, oh = img.size
        if ow > effective.max_edge_px or oh > effective.max_edge_px:
            img, _ = _fit_within_max_edge(img, effective.max_edge_px)
            policy_mismatch = True
        img, contained = _contain_to_policy_box(img, effective)
        policy_mismatch = policy_mismatch or contained
    else:
        if reuse_only:
            raise RenderMapboxStillError(
                f"{location_id}: no bundled_relative and --reuse-only set",
                EXIT_MISSING_TOKEN,
            )
        if not allow_network:
            raise RenderMapboxStillError(
                f"{location_id}: network render disabled; pass --allow-network to call Mapbox Static API",
                EXIT_MISSING_TOKEN,
            )
        token = _mapbox_access_token()
        if not token:
            raise RenderMapboxStillError(
                "MAPBOX_ACCESS_TOKEN (or MAPBOX_TOKEN) required for render path",
                EXIT_MISSING_TOKEN,
            )
        raw = _fetch_mapbox_static_image(
            center_lon,
            center_lat,
            effective.zoom,
            effective.width_px,
            effective.height_px,
            effective.style_id,
            token,
        )
        img = _load_image_from_bytes(raw)
        source_label = "mapbox_static"
        img, _ = _fit_within_max_edge(img, effective.max_edge_px)

    assert img is not None
    jpeg = _jpeg_bytes(img)
    sha = _sha256_hex(jpeg)
    wpx, hpx = img.size

    try:
        bundle_rel = dest_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        bundle_rel = rel_out.replace("\\", "/")

    record = {
        "location_id": location_id,
        "map_id": map_id,
        "still_bundled_resource": bundle_rel,
        "still_bundle_id": f"nutonic.still.v1.{location_id}",
        "still_sha256": sha,
        "width_px": wpx,
        "height_px": hpx,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "zoom": effective.zoom,
        "style_id": effective.style_id,
        "still_policy_mismatch": policy_mismatch,
        "source": source_label,
    }

    if dry_run:
        return record

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_stills_dir.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(jpeg)
    cache_jpeg_path.write_bytes(jpeg)
    meta_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render or reuse Mapbox reference stills for catalog locations.")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument(
        "--compose-resources-maps-dir",
        type=Path,
        default=REPO_ROOT / "nutonic" / "shared" / "src" / "commonMain" / "composeResources" / "files" / "maps",
    )
    p.add_argument(
        "--meta-dir",
        type=Path,
        default=REPO_ROOT / "data" / "cache" / "build_stills",
        help="Writes per-location *.meta.json under meta-dir/stills/ and still_index.json at meta-dir/",
    )
    p.add_argument("--still-policy", type=Path, default=None)
    p.add_argument("--reuse-only", action="store_true")
    p.add_argument(
        "--allow-network",
        action="store_true",
        help="Permit Mapbox Static Images HTTP fetch when catalog row has no bundled_relative.",
    )
    p.add_argument("--dry-run", action="store_true")
    ns = p.parse_args(argv)

    catalog_root = ns.catalog_root.resolve()
    compose_maps = ns.compose_resources_maps_dir.resolve()
    meta_dir = ns.meta_dir.resolve()
    meta_stills = meta_dir / "stills"

    base_policy = load_still_policy_file(ns.still_policy)
    rows: list[dict[str, Any]] = []
    try:
        for ypath in _list_location_files(catalog_root):
            data = _load_yaml_mapping(ypath)
            lid = str(data.get("location_id") or ypath.stem)
            mid = str(data.get("map_id") or lid)
            try:
                lat = float(data["truth_lat"])
                lon = float(data["truth_lon"])
            except (KeyError, TypeError, ValueError) as e:
                raise RenderMapboxStillError(f"{ypath}: invalid truth_lat/truth_lon", 2) from e
            src = data.get("still_source")
            rec = process_location(
                lid,
                mid,
                lat,
                lon,
                src if isinstance(src, dict) else None,
                base_policy,
                repo_root=REPO_ROOT,
                compose_maps_dir=compose_maps,
                meta_stills_dir=meta_stills,
                reuse_only=bool(ns.reuse_only),
                allow_network=bool(ns.allow_network),
                dry_run=bool(ns.dry_run),
            )
            rows.append(rec)
    except RenderMapboxStillError as e:
        print(str(e), file=sys.stderr)
        return int(e.code)

    index = {"locations": sorted(rows, key=lambda r: r["location_id"])}
    if not ns.dry_run:
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "still_index.json").write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
