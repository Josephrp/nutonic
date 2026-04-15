"""Sentinel fetch mode vs TiM branch matrix (plan §5.3)."""

from __future__ import annotations

from enum import StrEnum


class SentinelFetchMode(StrEnum):
    MINIMAL_RGB = "MINIMAL_RGB"
    TERRAMIND_SPECTRAL = "TERRAMIND_SPECTRAL"
    FULL_STAC = "FULL_STAC"


class TimBranch(StrEnum):
    S2L2A_FULL = "S2L2A_full"
    RGB_MAPBOX = "RGB_mapbox"


def validate_mode_matrix(
    *,
    sentinel_fetch_mode: SentinelFetchMode,
    tim_branch: TimBranch,
    enable_tim: bool,
) -> str | None:
    """Return error code string if invalid; else None."""
    if sentinel_fetch_mode == SentinelFetchMode.MINIMAL_RGB:
        if enable_tim and tim_branch != TimBranch.RGB_MAPBOX:
            return "TIM_BRANCH_REQUIRES_RGB_MAPBOX"
        return None
    if sentinel_fetch_mode == SentinelFetchMode.TERRAMIND_SPECTRAL:
        if enable_tim and tim_branch != TimBranch.S2L2A_FULL:
            return "TIM_BRANCH_REQUIRES_S2L2A_FULL"
        return None
    if sentinel_fetch_mode == SentinelFetchMode.FULL_STAC:
        if enable_tim and tim_branch not in (TimBranch.S2L2A_FULL, TimBranch.RGB_MAPBOX):
            return "TIM_BRANCH_INVALID"
        return None
    return None
