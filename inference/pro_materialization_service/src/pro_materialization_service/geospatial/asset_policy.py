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


class AnalysisProfile(StrEnum):
    WILDFIRE = "wildfire"
    OCEANSCOUT_SHIP_DETECTION = "oceanscout_ship_detection"
    LAND_USE_CHANGE = "land_use_change"
    FLOOD_PULSE = "flood_pulse"
    BRIEF_ONLY = "brief_only"


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


def validate_profile_mode_matrix(
    *,
    analysis_profile: AnalysisProfile,
    sentinel_fetch_mode: SentinelFetchMode,
    enable_tim: bool,
) -> str | None:
    """Return error code string if a mini-app profile asks for an impossible mode."""
    if analysis_profile == AnalysisProfile.BRIEF_ONLY:
        return None
    if analysis_profile in (
        AnalysisProfile.WILDFIRE,
        AnalysisProfile.OCEANSCOUT_SHIP_DETECTION,
        AnalysisProfile.LAND_USE_CHANGE,
        AnalysisProfile.FLOOD_PULSE,
    ):
        if not enable_tim:
            return "PROFILE_REQUIRES_TIM"
        if sentinel_fetch_mode == SentinelFetchMode.MINIMAL_RGB:
            return "PROFILE_REQUIRES_SENTINEL_STACK"
    return None
