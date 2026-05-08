"""Build ``PanosSampleResponse`` using Google Street View Static + Metadata."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
from typing import Any

from streetview_pano_service.errors import StreetViewInsufficientCoverageError, StreetViewMetadataError
from streetview_pano_service.google_static import fetch_metadata, fetch_static_jpeg, offset_lat_lon
from streetview_pano_service.models import (
    CenterWgs84,
    PanoFrame,
    PanosSampleRequest,
    PanosSampleResponse,
    resolve_jitter_seed,
)
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


def _static_fov_pitch(req: PanosSampleRequest, rng: random.Random) -> tuple[int, float]:
    fov = int(req.fov_deg) if req.fov_deg is not None else 75
    jitter = float(req.pitch_jitter_deg or 0.0)
    pitch = rng.uniform(-jitter, jitter) if jitter > 0 else 0.0
    return fov, pitch


def _cache_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def sample_panos_google_legacy_radial(req: PanosSampleRequest, *, api_key: str) -> PanosSampleResponse:
    """Deterministic radial offsets + ``i·360/n`` headings (location-based Static only)."""
    c: CenterWgs84 = req.center
    meta = fetch_metadata(c.lat, c.lon, api_key=api_key)
    pano_id_center = meta.pano_id
    if meta.status != "OK":
        raise StreetViewMetadataError(
            f"Street View metadata status={meta.status!r} at center ({c.lat}, {c.lon})",
            status=meta.status,
        )
    n = req.count
    frames: list[PanoFrame] = []
    w, h = int(req.image_width), int(req.image_height)
    for i in range(n):
        heading = (i * (360.0 / max(n, 1))) % 360.0
        frac = (i + 1) / max(n, 1)
        dist = min(float(req.radius_m), 120.0) * frac
        plat, plon = offset_lat_lon(c.lat, c.lon, distance_m=dist, bearing_deg=heading)
        jpeg = fetch_static_jpeg(
            lat=plat,
            lon=plon,
            api_key=api_key,
            heading=heading,
            pitch=0.0,
            fov=75,
            width=w,
            height=h,
        )
        b64 = base64.b64encode(jpeg).decode("ascii")
        pid = str(pano_id_center) if pano_id_center else f"google-{req.request_id[:8]}-{i}"
        frames.append(
            PanoFrame(
                pano_id=f"{pid}-{i}",
                heading_deg=heading,
                pitch_deg=0.0,
                image_base64=b64,
                attribution="© Google (Street View Static API)",
            )
        )
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    digest = _cache_digest(
        {
            "mode": "LEGACY_RADIAL_OFFSET",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "radius_m": float(req.radius_m),
            "seed": seed,
            "w": w,
            "h": h,
        }
    )
    dbg: dict[str, Any] | None = None
    if _expose_debug():
        dbg = {
            "sampling_mode": "LEGACY_RADIAL_OFFSET",
            "R_m": None,
            "jitter_seed": seed,
            "attempts": n,
            "zero_results_drops": 0,
            "accepted": n,
        }
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04-google",
        sampling_debug=dbg,
    )


def sample_panos_google_omni_single_pano(req: PanosSampleRequest, *, api_key: str) -> PanosSampleResponse:
    """One metadata at center; ``N`` Static calls, same ``pano_id`` when present, headings ``i·360/N``."""
    c: CenterWgs84 = req.center
    meta = fetch_metadata(c.lat, c.lon, api_key=api_key)
    if meta.status != "OK":
        raise StreetViewMetadataError(
            f"Street View metadata status={meta.status!r} at center ({c.lat}, {c.lon})",
            status=meta.status,
        )
    pano_id = meta.pano_id
    slat = meta.lat if meta.lat is not None else c.lat
    slon = meta.lon if meta.lon is not None else c.lon
    n = req.count
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    rng = random.Random(seed)
    frames: list[PanoFrame] = []
    w, h = int(req.image_width), int(req.image_height)
    for i in range(n):
        heading = (i * (360.0 / max(n, 1))) % 360.0
        fov, pitch = _static_fov_pitch(req, rng)
        if pano_id:
            jpeg = fetch_static_jpeg(
                pano_id=pano_id,
                api_key=api_key,
                heading=heading,
                pitch=pitch,
                fov=fov,
                width=w,
                height=h,
            )
        else:
            jpeg = fetch_static_jpeg(
                lat=slat,
                lon=slon,
                api_key=api_key,
                heading=heading,
                pitch=pitch,
                fov=fov,
                width=w,
                height=h,
            )
        b64 = base64.b64encode(jpeg).decode("ascii")
        base = pano_id or f"google-{req.request_id[:8]}"
        frames.append(
            PanoFrame(
                pano_id=f"{base}-omni-{i}",
                heading_deg=heading,
                pitch_deg=pitch,
                image_base64=b64,
                attribution="© Google (Street View Static API)",
            )
        )
    digest = _cache_digest(
        {
            "mode": "OMNI_SINGLE_PANO",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "seed": seed,
            "w": w,
            "h": h,
            "fov": int(req.fov_deg) if req.fov_deg is not None else 75,
            "pitch_j": float(req.pitch_jitter_deg or 0.0),
        }
    )
    dbg: dict[str, Any] | None = None
    if _expose_debug():
        dbg = {
            "sampling_mode": "OMNI_SINGLE_PANO",
            "R_m": None,
            "jitter_seed": seed,
            "metadata_status": meta.status,
            "pano_id_present": bool(pano_id),
        }
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04-google",
        sampling_debug=dbg,
    )


def sample_panos_google_stochastic(req: PanosSampleRequest, *, api_key: str) -> PanosSampleResponse:
    """Seeded random anchors in disk **R**, metadata per anchor, random heading per frame."""
    c: CenterWgs84 = req.center
    seed = resolve_jitter_seed(req.request_id, req.jitter_seed)
    rng = random.Random(seed)
    r_m = clamp_area_radius_m(req.area_radius_m)
    n = req.count
    max_attempts = MAX_METADATA_ATTEMPTS_FACTOR * max(n, 1)
    accepted: list[tuple[float, float]] = []
    frames: list[PanoFrame] = []
    w, h = int(req.image_width), int(req.image_height)
    attempts = 0
    zero_drops = 0
    min_sep = req.min_anchor_separation_m
    dbg_on = _expose_debug()

    while len(frames) < n and attempts < max_attempts:
        attempts += 1
        alat, alon = uniform_disk_offset(rng, c.lat, c.lon, r_m)
        meta = fetch_metadata(alat, alon, api_key=api_key)
        if meta.status != "OK":
            if meta.status == "ZERO_RESULTS":
                zero_drops += 1
            continue
        if min_sep is not None and min_sep > 0:
            if any(haversine_m(alat, alon, pl, pm) < float(min_sep) for pl, pm in accepted):
                continue
        pano_id = meta.pano_id
        slat = meta.lat if meta.lat is not None else alat
        slon = meta.lon if meta.lon is not None else alon
        heading = rng.uniform(0.0, 360.0)
        fov, pitch = _static_fov_pitch(req, rng)
        try:
            if pano_id:
                jpeg = fetch_static_jpeg(
                    pano_id=pano_id,
                    api_key=api_key,
                    heading=heading,
                    pitch=pitch,
                    fov=fov,
                    width=w,
                    height=h,
                )
            else:
                jpeg = fetch_static_jpeg(
                    lat=slat,
                    lon=slon,
                    api_key=api_key,
                    heading=heading,
                    pitch=pitch,
                    fov=fov,
                    width=w,
                    height=h,
                )
        except RuntimeError:
            continue
        b64 = base64.b64encode(jpeg).decode("ascii")
        base = pano_id or f"google-{req.request_id[:8]}"
        idx = len(frames)
        frames.append(
            PanoFrame(
                pano_id=f"{base}#{idx}",
                heading_deg=heading,
                pitch_deg=pitch,
                image_base64=b64,
                attribution="© Google (Street View Static API)",
                anchor_lat=alat if dbg_on else None,
                anchor_lon=alon if dbg_on else None,
            )
        )
        accepted.append((alat, alon))

    if len(frames) < n:
        raise StreetViewInsufficientCoverageError(
            f"Insufficient Street View coverage: got {len(frames)}/{n} frames after {attempts} attempts",
            debug={
                "sampling_mode": "STOCHASTIC_S2_FOOTPRINT",
                "R_m": r_m,
                "jitter_seed": seed,
                "attempts": attempts,
                "zero_results_drops": zero_drops,
                "accepted": len(frames),
            },
        )

    digest = _cache_digest(
        {
            "mode": "STOCHASTIC_S2_FOOTPRINT",
            "v": S2_AREA_POLICY_VERSION,
            "lat": round(c.lat, 6),
            "lon": round(c.lon, 6),
            "n": n,
            "R_m": round(r_m, 3),
            "seed": seed,
            "min_sep": min_sep,
            "w": w,
            "h": h,
            "fov": int(req.fov_deg) if req.fov_deg is not None else 75,
            "pitch_j": float(req.pitch_jitter_deg or 0.0),
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
        terms_version="2026-04-google",
        sampling_debug=dbg,
    )


def sample_panos_google(req: PanosSampleRequest, *, api_key: str) -> PanosSampleResponse:
    mode = req.sampling_mode
    if mode == "LEGACY_RADIAL_OFFSET":
        return sample_panos_google_legacy_radial(req, api_key=api_key)
    if mode == "OMNI_SINGLE_PANO":
        return sample_panos_google_omni_single_pano(req, api_key=api_key)
    return sample_panos_google_stochastic(req, api_key=api_key)
