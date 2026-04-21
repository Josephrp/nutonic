"""Leap-finetune VLM SFT rows (aligned with ``refs/satellite-vlm/prepare_vrsbench.py``)."""

from __future__ import annotations

import json
from typing import Any

CAPTIONING_PROMPT = (
    "The input is satellite imagery (RGB). Describe this imagery in detail, "
    "including surface cover and structure where visible."
)

MAPBOX_OVERVIEW_PROMPT = (
    "The input is overhead context imagery (not the same sensor as the chips). "
    "Describe it and relate it to the paired satellite imagery and land-cover outputs "
    "from the same area in this dataset."
)

CLASS_FOCUS_USER_PROMPT = (
    "The input is satellite imagery with an aligned per-pixel land-cover label. "
    "Describe only **{class_name}** in the imagery: approximate share of valid pixels and brief spatial layout."
)

GROUNDING_PROMPT = (
    "The input is satellite imagery. Inspect it and detect the {target}. "
    'Provide result as a valid JSON: [{{"label": str, "bbox": [x1,y1,x2,y2]}}, ...]. '
    "Coordinates must be normalized to 0-1."
)


def make_vlm_message(image_filename: str, user_text: str, assistant_text: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_filename},
                    {"type": "text", "text": user_text},
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_text}],
            },
        ]
    }


def caption_row(image_rel_path: str, caption: str) -> dict[str, Any]:
    return make_vlm_message(image_rel_path, CAPTIONING_PROMPT, caption)


def mapbox_overview_row(image_rel_path: str, caption: str) -> dict[str, Any]:
    return make_vlm_message(image_rel_path, MAPBOX_OVERVIEW_PROMPT, caption)


def class_focus_caption_row(image_rel_path: str, class_name: str, answer: str) -> dict[str, Any]:
    return make_vlm_message(image_rel_path, CLASS_FOCUS_USER_PROMPT.format(class_name=class_name), answer)


def grounding_row(image_rel_path: str, target: str, bbox_json: str) -> dict[str, Any]:
    return make_vlm_message(image_rel_path, GROUNDING_PROMPT.format(target=target), bbox_json)


def split_key(poi_id: str, *, buckets: int = 10) -> str:
    """Deterministic split: 0–7 train, 8 val, 9 test (stable across processes)."""
    import hashlib

    digest = hashlib.sha256(poi_id.encode("utf-8")).hexdigest()
    h = int(digest[:16], 16) % buckets
    if h <= 7:
        return "train"
    if h == 8:
        return "validation"
    return "test"


def write_jsonl(path: Any, rows: list[dict[str, Any]]) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def truncate_split_jsonl_files(data_dir: Path) -> None:
    """Create empty ``train.jsonl`` / ``validation.jsonl`` / ``test.jsonl`` for streaming builds."""
    from pathlib import Path

    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name in ("train", "validation", "test"):
        (d / f"{name}.jsonl").write_text("", encoding="utf-8")


def append_jsonl_row(path: Any, row: dict[str, Any]) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
