"""Build ``PanosSampleResponse`` using Google Street View Static + Metadata."""

from __future__ import annotations

import base64
import hashlib
import json

from streetview_pano_service.google_static import fetch_metadata, fetch_static_jpeg, offset_lat_lon
from streetview_pano_service.models import CenterWgs84, PanoFrame, PanosSampleRequest, PanosSampleResponse


def sample_panos_google(req: PanosSampleRequest, *, api_key: str) -> PanosSampleResponse:
    """
    ``count`` headings around ``center``, with slight radial offsets for decoy diversity.

    Uses one **metadata** call at the geometric center for a stable ``pano_id`` label when Google returns it.
    """
    c: CenterWgs84 = req.center
    meta = fetch_metadata(c.lat, c.lon, api_key=api_key)
    pano_id_center = meta.get("pano_id") if isinstance(meta, dict) else None
    st = meta.get("status") if isinstance(meta, dict) else None
    if st not in (None, "OK"):
        raise RuntimeError(f"Street View metadata status={st!r} at center ({c.lat}, {c.lon})")

    n = req.count
    frames: list[PanoFrame] = []
    w = int(req.image_width)
    h = int(req.image_height)
    for i in range(n):
        heading = (i * (360.0 / max(n, 1))) % 360.0
        frac = (i + 1) / max(n, 1)
        dist = min(float(req.radius_m), 120.0) * frac
        plat, plon = offset_lat_lon(c.lat, c.lon, distance_m=dist, bearing_deg=heading)
        jpeg = fetch_static_jpeg(
            plat,
            plon,
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
    digest = hashlib.sha256(json.dumps([c.lat, c.lon, n], sort_keys=True).encode()).hexdigest()
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04-google",
    )
