"""Derive reference bounding boxes from Sentinel-2 Scene Classification (SCL) for Patagonia eval."""

from __future__ import annotations

from typing import Any

import numpy as np

# Minimum fraction of chip pixels for a semantic mask to yield a gold box (avoid speckle).
MIN_AREA_FRACTION = 0.015

# ESA SCL classes used for coarse semantics (L2A).
SCL_WATER = 6
SCL_VEG = 4
SCL_BARE = 5
SCL_SNOW_ICE = 11

# Target.category → which semantic roles to extract as gold (aligned with eval geography types).
CATEGORY_GOLD_ROLES: dict[str, tuple[str, ...]] = {
    "marine_reserve": ("water",),
    "marine_reserve_offshore": ("water",),
    "marine_reserve_nearshore": ("water", "vegetation"),
    "marine_reserve_coastal": ("water", "vegetation"),
    "glacier_ice": ("snow_ice", "water"),
    "andean_forest_lake": ("water", "vegetation"),
    "urban_coastal_control": ("water", "vegetation"),
    "maritime_chokepoint_control": ("water", "vegetation"),
    "fjord_mountain_control": ("water", "snow_ice"),
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _mask_for_role(scl: np.ndarray, role: str) -> np.ndarray:
    if role == "water":
        return scl == SCL_WATER
    if role == "vegetation":
        return scl == SCL_VEG
    if role == "bare":
        return scl == SCL_BARE
    if role == "snow_ice":
        return scl == SCL_SNOW_ICE
    raise ValueError(f"unknown gold role {role!r}")


def _bbox_xyxy_from_mask(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    h, w = mask.shape
    frac = float(xs.size) / float(h * w)
    if frac < MIN_AREA_FRACTION:
        return None
    x1 = float(xs.min()) / float(w)
    y1 = float(ys.min()) / float(h)
    x2 = float(xs.max() + 1) / float(w)
    y2 = float(ys.max() + 1) / float(h)
    return (_clamp01(x1), _clamp01(y1), _clamp01(x2), _clamp01(y2))


def gold_boxes_from_scl(scl_hw: np.ndarray, *, category: str) -> list[dict[str, Any]]:
    """
    Build normalized [0,1] xyxy boxes from SCL for roles implied by ``category``.

    Each entry: ``{"label", "bbox", "source", "area_fraction"}``.
    """
    roles = CATEGORY_GOLD_ROLES.get(category.strip().lower(), ("water", "vegetation"))
    out: list[dict[str, Any]] = []
    h, w = scl_hw.shape
    for role in roles:
        mask = _mask_for_role(scl_hw, role)
        bb = _bbox_xyxy_from_mask(mask)
        if bb is None:
            continue
        frac = float(np.count_nonzero(mask)) / float(h * w)
        out.append(
            {
                "label": role,
                "bbox": [bb[0], bb[1], bb[2], bb[3]],
                "source": "sentinel2_scl",
                "area_fraction": round(frac, 5),
            }
        )
    return out
