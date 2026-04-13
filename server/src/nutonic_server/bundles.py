"""IMP-081: versioned still bytes served from packaged bundle ids."""

from __future__ import annotations

from pathlib import Path

_BUNDLE_FILES: dict[str, str] = {
    "nutonic.bundle.v1.demo_still": "nutonic.bundle.v1.demo_still.jpg",
}


def resolve_bundle_bytes(bundle_id: str) -> tuple[bytes, str] | None:
    """Return (body, media_type) for a known bundle id (JPEG still under ``nutonic_server/bundles/``)."""
    name = _BUNDLE_FILES.get(bundle_id.strip())
    if not name:
        return None
    here = Path(__file__).resolve().parent / "bundles" / name
    if here.is_file():
        return here.read_bytes(), "image/jpeg"
    return None
