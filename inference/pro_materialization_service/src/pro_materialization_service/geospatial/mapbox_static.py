"""Mapbox Static Images metadata only — runtime fetch has been removed."""

from __future__ import annotations

import os

MAPBOX_STYLE = "mapbox/satellite-v9"
MAPBOX_STATIC_BASE = "https://api.mapbox.com/styles/v1"
MAPBOX_ATTRIBUTION = "© Mapbox © OpenStreetMap © Maxar"


def mapbox_style() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_STATIC_STYLE") or os.environ.get("MAPBOX_STATIC_STYLE") or MAPBOX_STYLE
    ).strip()


def mapbox_static_base() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_STATIC_BASE")
        or os.environ.get("MAPBOX_STATIC_BASE")
        or MAPBOX_STATIC_BASE
    ).strip().rstrip("/")


def mapbox_attribution() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_ATTRIBUTION")
        or os.environ.get("MAPBOX_ATTRIBUTION")
        or MAPBOX_ATTRIBUTION
    ).strip()


def mapbox_timeout_seconds() -> float:
    return _env_float(
        "NUTONIC_MAPBOX_TIMEOUT_SECONDS",
        "MAPBOX_TIMEOUT_SECONDS",
        default=120.0,
        minimum=1.0,
    )


def mapbox_retry_count() -> int:
    return _env_int("NUTONIC_MAPBOX_RETRY_COUNT", "MAPBOX_RETRY_COUNT", default=1, minimum=0)


def mapbox_source_metadata() -> dict[str, str]:
    return {
        "provider": "mapbox",
        "style": mapbox_style(),
        "static_base": mapbox_static_base(),
        "attribution": mapbox_attribution(),
    }


def _env_float(*names: str, default: float, minimum: float) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(minimum, float(raw.strip()))
        except ValueError:
            return default
    return default


def _env_int(*names: str, default: int, minimum: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(minimum, int(raw.strip()))
        except ValueError:
            return default
    return default
