"""Draw axis-aligned boxes on uint8 RGB chips (dataset QA / visualization)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

# Distinct outlines for arbitrary class names (cycles).
_PALETTE: list[tuple[int, int, int]] = [
    (255, 59, 48),
    (52, 199, 89),
    (0, 122, 255),
    (255, 149, 0),
    (175, 82, 222),
    (255, 204, 0),
    (90, 200, 250),
    (88, 86, 214),
    (255, 45, 85),
    (162, 162, 162),
]


def _color_for_label(label: str) -> tuple[int, int, int]:
    return _PALETTE[abs(hash(label)) % len(_PALETTE)]


def _clamp_xyxy(
    xyxy: tuple[int, int, int, int],
    w: int,
    h: int,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = xyxy
    x1 = max(0, min(w - 1, int(x1)))
    x2 = max(0, min(w - 1, int(x2)))
    y1 = max(0, min(h - 1, int(y1)))
    y2 = max(0, min(h - 1, int(y2)))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def write_bbox_overlay_png(
    rgb_hw3: np.ndarray,
    boxes: Sequence[tuple[str, tuple[int, int, int, int]]],
    out_path: Path,
    *,
    line_width: int = 2,
) -> None:
    """
    Save ``rgb_hw3`` with rectangles for each ``(label, (x1,y1,x2,y2))`` in pixel coords.

    Empty ``boxes`` writes a copy of the RGB image.
    """
    if rgb_hw3.ndim != 3 or rgb_hw3.shape[2] != 3:
        raise ValueError("rgb_hw3 must be H×W×3 uint8")
    h, w = rgb_hw3.shape[0], rgb_hw3.shape[1]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(rgb_hw3).copy()
    draw = ImageDraw.Draw(im)
    lw = max(1, int(line_width))
    for label, xyxy in boxes:
        x1, y1, x2, y2 = _clamp_xyxy(xyxy, w, h)
        if x2 <= x1 or y2 <= y1:
            continue
        color = _color_for_label(label)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=lw)
    im.save(out_path, format="PNG", optimize=True)
