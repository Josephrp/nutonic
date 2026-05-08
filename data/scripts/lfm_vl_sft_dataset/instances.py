"""Dynamic World class names, connected-component boxes, rule captions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# Google Dynamic World V1 label classes (0–8). Names stable for JSONL.
DYNAMIC_WORLD_CLASSES: dict[int, str] = {
    0: "water",
    1: "trees",
    2: "grass",
    3: "flooded_vegetation",
    4: "crops",
    5: "shrub_and_scrub",
    6: "built",
    7: "bare_ground",
    8: "snow_and_ice",
}


@dataclass
class RegionAnn:
    bbox_xyxy: tuple[int, int, int, int]
    label: str
    class_id: int
    area_px: int


def extract_regions(
    mask_hw: np.ndarray,
    *,
    min_area_px: int = 50,
    max_per_class: int = 32,
    ignore_value: int = 255,
) -> list[RegionAnn]:
    """8-connected components via ``scipy.ndimage`` (no ``scikit-image``)."""
    from scipy import ndimage

    struct = ndimage.generate_binary_structure(2, 2)
    out: list[RegionAnn] = []
    for class_id in np.unique(mask_hw):
        cid = int(class_id)
        if cid == ignore_value or cid not in DYNAMIC_WORLD_CLASSES:
            continue
        binary = (mask_hw == cid).astype(np.uint8)
        labeled, nfeat = ndimage.label(binary, structure=struct)
        comps: list[tuple[int, int, int, int, int]] = []
        for comp in range(1, nfeat + 1):
            ys, xs = np.nonzero(labeled == comp)
            if ys.size == 0:
                continue
            area = int(ys.size)
            if area < min_area_px:
                continue
            minr, maxr = int(ys.min()), int(ys.max())
            minc, maxc = int(xs.min()), int(xs.max())
            comps.append((area, minc, minr, maxc, maxr))
        comps.sort(key=lambda t: -t[0])
        for area, minc, minr, maxc, maxr in comps[:max_per_class]:
            out.append(
                RegionAnn(
                    bbox_xyxy=(minc, minr, maxc, maxr),
                    label=DYNAMIC_WORLD_CLASSES[cid],
                    class_id=cid,
                    area_px=area,
                )
            )
    return out


def class_pixel_fractions(mask_hw: np.ndarray, *, ignore_value: int = 255) -> dict[int, float]:
    """Pixel fraction per Dynamic World class id (0–8) over valid (non-``ignore_value``) pixels."""
    flat = mask_hw.ravel()
    valid = flat != ignore_value
    n = int(np.sum(valid))
    if n <= 0:
        return {}
    out: dict[int, float] = {}
    for cid in range(9):
        cnt = int(np.sum((flat == cid) & valid))
        if cnt > 0:
            out[cid] = cnt / float(n)
    return out


def class_focus_sentence(class_id: int, fraction: float, *, regions: list[RegionAnn]) -> str:
    """One-sentence assistant text for a class-focused caption row."""
    name = DYNAMIC_WORLD_CLASSES[class_id]
    cls_regs = [r for r in regions if r.class_id == class_id]
    ncomp = len(cls_regs)
    if ncomp == 0:
        layout = "spatially mixed appearance in this resolution."
    elif ncomp <= 2:
        layout = "one or two dominant contiguous patches."
    elif ncomp <= 5:
        layout = "several separated patches."
    else:
        layout = "many small fragments across the tile."
    return (
        f"In this satellite imagery, **{name}** accounts for about {round(fraction * 100, 1)}% "
        f"of valid pixels, showing {layout}"
    )


def rule_caption(regions: list[RegionAnn], *, image_w: int, image_h: int, top_k: int = 4) -> str:
    """Deterministic caption from region areas (``mask`` and ``regions`` same resolution)."""
    area_total = float(image_w * image_h)
    if not regions:
        return (
            "This satellite imagery shows no clear land-cover regions above the size threshold "
            "in the model output resolution."
        )

    by_label: dict[str, int] = {}
    for r in regions:
        by_label[r.label] = by_label.get(r.label, 0) + r.area_px

    sorted_items = sorted(by_label.items(), key=lambda x: x[1], reverse=True)[:top_k]
    parts = [f"{lab} ({round(100.0 * a / area_total, 1)}%)" for lab, a in sorted_items]
    if len(parts) == 1:
        body = parts[0]
    else:
        body = ", ".join(parts[:-1]) + f", and {parts[-1]}"
    return f"This satellite imagery is dominated by {body}."


def regions_to_normalized_json(regions: list[RegionAnn], *, image_w: int, image_h: int) -> str:
    import json

    objs: list[dict[str, Any]] = []
    for r in regions:
        x1, y1, x2, y2 = r.bbox_xyxy
        objs.append(
            {
                "label": r.label,
                "bbox": [
                    round(x1 / image_w, 4),
                    round(y1 / image_h, 4),
                    round(x2 / image_w, 4),
                    round(y2 / image_h, 4),
                ],
            }
        )
    return json.dumps(objs)
