"""Connected-component regions for binary change masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage


@dataclass
class ChangeRegion:
    """Axis-aligned region detected from a change mask."""

    bbox_xyxy: tuple[int, int, int, int]
    label: str
    area_px: int
    score: float | None = None


def find_change_regions(
    change_mask: np.ndarray,
    min_area_px: int = 100,
    max_regions: int = 20,
    label_name: str = "change",
    score_map: np.ndarray | None = None,
) -> list[ChangeRegion]:
    """
    Connected components on a binary mask.

    `change_mask` may be bool, numeric, or uint8; any value > 0 is treated as change.
    If `score_map` is provided, each region score is mean(score_map[pixels]).
    """
    binary = np.asarray(change_mask) > 0
    struct = ndimage.generate_binary_structure(2, 2)
    labeled, nfeat = ndimage.label(binary.astype(np.uint8), structure=struct)
    regions: list[ChangeRegion] = []
    for comp in range(1, nfeat + 1):
        ys, xs = np.nonzero(labeled == comp)
        if ys.size == 0:
            continue
        area = int(ys.size)
        if area < int(min_area_px):
            continue
        minr, maxr = int(ys.min()), int(ys.max())
        minc, maxc = int(xs.min()), int(xs.max())
        score: float | None = None
        if score_map is not None:
            vals = np.asarray(score_map)[ys, xs]
            vals = vals[np.isfinite(vals)]
            if vals.size > 0:
                score = float(vals.mean())
        regions.append(
            ChangeRegion(
                bbox_xyxy=(minc, minr, maxc, maxr),
                label=label_name,
                area_px=area,
                score=score,
            )
        )
    regions.sort(key=lambda r: r.area_px, reverse=True)
    return regions[: max(0, int(max_regions))]


def regions_to_normalized_json(
    regions: list[ChangeRegion],
    *,
    image_w: int,
    image_h: int,
) -> str:
    import json

    objs: list[dict[str, Any]] = []
    iw = max(1, int(image_w))
    ih = max(1, int(image_h))
    for r in regions:
        x1, y1, x2, y2 = r.bbox_xyxy
        obj: dict[str, Any] = {
            "label": r.label,
            "bbox": [
                round(x1 / iw, 4),
                round(y1 / ih, 4),
                round(x2 / iw, 4),
                round(y2 / ih, 4),
            ],
        }
        if r.score is not None:
            obj["score"] = round(float(r.score), 4)
        objs.append(obj)
    return json.dumps(objs)

