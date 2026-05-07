"""Derive reference bounding boxes from Sentinel-2 Scene Classification (SCL) for Patagonia eval."""

from __future__ import annotations

from typing import Any

import numpy as np

# Minimum fraction of chip pixels for a semantic mask to yield any gold (avoid speckle).
MIN_AREA_FRACTION = 0.015
# Minimum component size; if all components are smaller, fall back to a bbox over the full mask.
MIN_COMPONENT_FRACTION = 0.01
MAX_COMPONENTS_PER_ROLE = 2

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


def _largest_components(mask: np.ndarray, *, max_components: int) -> list[np.ndarray]:
    """Return up to N largest 4-neighborhood connected components as boolean masks."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=np.uint8)
    comps: list[tuple[int, np.ndarray]] = []
    # Iterate only over true pixels
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist(), strict=False):
        if seen[y0, x0]:
            continue
        # BFS/stack
        stack = [(y0, x0)]
        seen[y0, x0] = 1
        coords: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            coords.append((y, x))
            if y > 0 and mask[y - 1, x] and not seen[y - 1, x]:
                seen[y - 1, x] = 1
                stack.append((y - 1, x))
            if y + 1 < h and mask[y + 1, x] and not seen[y + 1, x]:
                seen[y + 1, x] = 1
                stack.append((y + 1, x))
            if x > 0 and mask[y, x - 1] and not seen[y, x - 1]:
                seen[y, x - 1] = 1
                stack.append((y, x - 1))
            if x + 1 < w and mask[y, x + 1] and not seen[y, x + 1]:
                seen[y, x + 1] = 1
                stack.append((y, x + 1))
        if not coords:
            continue
        cm = np.zeros((h, w), dtype=bool)
        for y, x in coords:
            cm[y, x] = True
        comps.append((len(coords), cm))
    comps.sort(key=lambda t: t[0], reverse=True)
    return [cm for _, cm in comps[: max(1, int(max_components))]]


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
        total_frac = float(np.count_nonzero(mask)) / float(h * w)
        if total_frac < MIN_AREA_FRACTION:
            continue
        comps = _largest_components(mask, max_components=MAX_COMPONENTS_PER_ROLE)
        emitted = 0
        for cm in comps:
            comp_frac = float(np.count_nonzero(cm)) / float(h * w)
            if comp_frac < MIN_COMPONENT_FRACTION:
                continue
            bb = _bbox_xyxy_from_mask(cm)
            if bb is None:
                continue
            out.append(
                {
                    "label": role,
                    "bbox": [bb[0], bb[1], bb[2], bb[3]],
                    "source": "sentinel2_scl_component",
                    "area_fraction": round(comp_frac, 5),
                    "area_fraction_total": round(total_frac, 5),
                }
            )
            emitted += 1
            if emitted >= MAX_COMPONENTS_PER_ROLE:
                break
        if emitted == 0:
            # Avoid `no_gold` when the class is present but fragmented. Use full-mask bbox.
            bb = _bbox_xyxy_from_mask(mask)
            if bb is None:
                continue
            out.append(
                {
                    "label": role,
                    "bbox": [bb[0], bb[1], bb[2], bb[3]],
                    "source": "sentinel2_scl_fallback_fullmask",
                    "area_fraction": round(total_frac, 5),
                    "area_fraction_total": round(total_frac, 5),
                }
            )
    return out
