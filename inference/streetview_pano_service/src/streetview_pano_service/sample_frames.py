"""Deterministic stub frames (JPEG) for local batch runs without Google keys."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO

from PIL import Image

from streetview_pano_service.models import CenterWgs84, PanoFrame, PanosSampleRequest, PanosSampleResponse


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


def sample_panos_stub(req: PanosSampleRequest) -> PanosSampleResponse:
    """
    Return ``count`` synthetic frames around ``center`` (no network).

    ``pano_id`` values are stable decoy ids suitable for ``viewpoint_id`` downstream.
    """
    c: CenterWgs84 = req.center
    frames: list[PanoFrame] = []
    n = req.count
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
    digest = hashlib.sha256(f"{c.lat:.6f},{c.lon:.6f},{n}".encode()).hexdigest()
    return PanosSampleResponse(
        request_id=req.request_id,
        frames=frames,
        cache_key=f"sha256:{digest}",
        terms_version="2026-04",
    )
