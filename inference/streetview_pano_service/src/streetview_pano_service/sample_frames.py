"""Deterministic stub frames (JPEG) for local batch runs without Google keys."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
from io import BytesIO
from typing import Any

from PIL import Image

from streetview_pano_service.errors import StreetViewInsufficientCoverageError
from streetview_pano_service.models import CenterWgs84, PanoFrame, PanosSampleRequest, PanosSampleResponse, resolve_jitter_seed
from streetview_pano_service.sampling_extent import (
    S2_AREA_POLICY_VERSION,
    clamp_area_radius_m,
    haversine_m,
    MAX_METADATA_ATTEMPTS_FACTOR,
    uniform_disk_offset,
)


def _expose_debug() -> bool:
    v = os.environ.get("STREETVIEW_EXPOSE_SAMPLING_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _jpeg_b64(width: int, height: int, *, hue: int) -> str:
    """Encode a solid-ish JPEG; ``hue`` rotates RGB so frames differ per heading."""
    w = max(32, min(width, 1024))
    h = max(32, min(height, 1024))
    r = (hue * 7) % 256
    g = (hue * 13 + 80) % 256
    b = (hue * 3 + 140) % 256
    img = Image.new("RGB", (w, h), color=(r, g, b))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _cache_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _stub_stochastic(req: PanosSampleRequest) -> PanosSampleResponse:
    c: CenterWgs84 = req.center
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    rng = random.Random(seed)
    r_m = clamp_area_radius_m(req.area_radius_m)
    n = req.count
    max_attempts = MAX_METADATA_ATTEMPTS_FACTOR * max(n, 1)
    accepted: list[tuple[float, float]] = []
    frames: list[PanoFrame] = []
    attempts = 0
    zero_drops = 0  # stub has no metadata failures; kept for debug shape parity
    min_sep = req.min_anchor_separation_m
    dbg_on = _expose_debug()

    while len(frames) < n and attempts < max_attempts:
        attempts += 1
        alat, alon = uniform_disk_offset(rng, c.lat, c.lon, r_m)
        if min_sep is not None and min_sep > 0:
            if any(haversine_m(alat, alon, pl, pm) < float(min_sep) for pl, pm in accepted):
                continue
        heading = rng.uniform(0.0, 360.0)
        hue = int((heading + alat * 11.0 + alon * 7.0) % 360)
        b64 = _jpeg_b64(req.image_width, req.image_height, hue=hue)
        idx = len(frames)
        frames.append(
            PanoFrame(
                pano_id=f"stub-pano-{req.request_id[:8]}-{idx}",
                heading_deg=heading,
                pitch_deg=0.0,
                image_base64=b64,
                attribution="© Stub (local dev — no Google imagery)",
                anchor_lat=alat if dbg_on else None,
                anchor_lon=alon if dbg_on else None,
            )
        )
        accepted.append((alat, alon))

    if len(frames) < n:
        raise StreetViewInsufficientCoverageError(
            f"Stub stochastic: insufficient synthetic anchors ({len(frames)}/{n})",
            debug={"attempts": attempts, "zero_results_drops": zero_drops},
        )

    digest = _cache_digest(
        {
            "stub": True,
            "mode": "STOCHASTIC_S2_FOOTPRINT",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "R_m": round(r_m, 3),
            "seed": seed,
            "min_sep": min_sep,
            "w": int(req.image_width),
            "h": int(req.image_height),
        }
    )
    dbg: dict[str, Any] | None = None
    if dbg_on:
        dbg = {
            "sampling_mode": "STOCHASTIC_S2_FOOTPRINT",
            "R_m": r_m,
            "jitter_seed": seed,
            "attempts": attempts,
            "zero_results_drops": zero_drops,
            "accepted": len(frames),
        }
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04",
        sampling_debug=dbg,
    )


def _stub_legacy(req: PanosSampleRequest) -> PanosSampleResponse:
    c: CenterWgs84 = req.center
    frames: list[PanoFrame] = []
    n = req.count
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    for i in range(n):
        heading = (i * (360.0 / max(n, 1))) % 360.0
        hue = int((heading + c.lat * 11.0 + c.lon * 7.0) % 360)
        b64 = _jpeg_b64(req.image_width, req.image_height, hue=hue)
        pid = f"stub-pano-{req.request_id[:8]}-{i}"
        frames.append(
            PanoFrame(
                pano_id=pid,
                heading_deg=heading,
                pitch_deg=0.0,
                image_base64=b64,
                attribution="© Stub (local dev — no Google imagery)",
            )
        )
    digest = _cache_digest(
        {
            "stub": True,
            "mode": "LEGACY_RADIAL_OFFSET",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "radius_m": float(req.radius_m),
            "seed": seed,
            "w": int(req.image_width),
            "h": int(req.image_height),
        }
    )
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04",
        sampling_debug=None,
    )


def _stub_omni(req: PanosSampleRequest) -> PanosSampleResponse:
    c: CenterWgs84 = req.center
    n = req.count
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    rng = random.Random(seed)
    frames: list[PanoFrame] = []
    for i in range(n):
        heading = (i * (360.0 / max(n, 1))) % 360.0
        hue = int((heading + c.lat * 11.0 + c.lon * 7.0) % 360)
        b64 = _jpeg_b64(req.image_width, req.image_height, hue=hue)
        frames.append(
            PanoFrame(
                pano_id=f"stub-pano-{req.request_id[:8]}-omni-{i}",
                heading_deg=heading,
                pitch_deg=0.0,
                image_base64=b64,
                attribution="© Stub (local dev — no Google imagery)",
            )
        )
    digest = _cache_digest(
        {
            "stub": True,
            "mode": "OMNI_SINGLE_PANO",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "seed": seed,
            "w": int(req.image_width),
            "h": int(req.image_height),
        }
    )
    dbg: dict[str, Any] | None = None
    if _expose_debug():
        dbg = {"sampling_mode": "OMNI_SINGLE_PANO", "jitter_seed": seed, "R_m": None}
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04",
        sampling_debug=dbg,
    )


def sample_panos_stub(req: PanosSampleRequest) -> PanosSampleResponse:
    """
    Return ``count`` synthetic frames around ``center`` (no network).

    Mirrors Google sampling modes for cache keys and heading layout.
    """
    mode = req.sampling_mode
    if mode == "LEGACY_RADIAL_OFFSET":
        return _stub_legacy(req)
    if mode == "OMNI_SINGLE_PANO":
        return _stub_omni(req)
    return _stub_stochastic(req)
