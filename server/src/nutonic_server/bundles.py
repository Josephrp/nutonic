"""IMP-081: versioned still bytes served from packaged bundle ids."""

from __future__ import annotations

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).resolve().parent / "bundles" / "registry.json"


def _load_bundle_filenames() -> dict[str, str]:
    if not _REGISTRY_PATH.is_file():
        raise FileNotFoundError(
            f"Bundle registry missing: {_REGISTRY_PATH} (IMP-081; add JPEGs under bundles/ and map ids here).",
        )
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    bundles = raw.get("bundles")
    if not isinstance(bundles, dict) or not bundles:
        raise ValueError(f"{_REGISTRY_PATH}: expected non-empty 'bundles' object")
    return {str(k): str(v) for k, v in bundles.items()}


_BUNDLE_FILES: dict[str, str] = _load_bundle_filenames()


def resolve_bundle_bytes(bundle_id: str) -> tuple[bytes, str] | None:
    """Return (body, media_type) for a known bundle id (JPEG still under ``nutonic_server/bundles/``)."""
    name = _BUNDLE_FILES.get(bundle_id.strip())
    if not name:
        return None
    here = Path(__file__).resolve().parent / "bundles" / name
    if here.is_file():
        return here.read_bytes(), "image/jpeg"
    return None


def list_registered_bundle_ids() -> frozenset[str]:
    """Stable ids from ``registry.json`` (for tests / diagnostics)."""
    return frozenset(_BUNDLE_FILES.keys())
