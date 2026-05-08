from __future__ import annotations

import json
from typing import Any

from nutonic_pro_gradio_demo.models import ProVlmBoundingBox, ProVlmResult


def parse_vlm_output(
    *,
    raw_text: str,
    model_bundle_id: str | None,
    revision: str | None,
    source: str = "hf_space_vlm",
) -> ProVlmResult:
    raw = (raw_text or "").strip()
    parsed = _parse_json_candidate(raw)
    caption = _caption_from(parsed=parsed, raw=raw)
    boxes = _boxes_from(parsed) if isinstance(parsed, dict) else []
    return ProVlmResult(
        caption=caption[:2000],
        boxes=boxes,
        model_bundle_id=model_bundle_id,
        revision=revision,
        source=source,
    )


def _parse_json_candidate(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    # Prefer the first JSON object if the model emits preamble text.
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    candidate = raw[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _caption_from(*, parsed: dict[str, Any] | None, raw: str) -> str:
    if isinstance(parsed, dict):
        for key in ("caption", "summary"):
            v = parsed.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # Fallback: text before JSON, or truncated raw.
    before = raw.split("{", 1)[0].strip()
    return before if before else raw[:500].strip()


def _boxes_from(parsed: dict[str, Any]) -> list[ProVlmBoundingBox]:
    raw_boxes = None
    for key in ("boxes", "bboxes", "detections"):
        v = parsed.get(key)
        if isinstance(v, list):
            raw_boxes = v
            break
    if raw_boxes is None:
        return []
    out: list[ProVlmBoundingBox] = []
    for item in raw_boxes:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip() or "object"
        bbox_val = item.get("bbox") if "bbox" in item else item.get("box")
        bbox = _coerce_bbox(bbox_val)
        if bbox is None:
            continue
        conf_val = item.get("confidence") if "confidence" in item else item.get("score")
        conf = None
        if isinstance(conf_val, (int, float)):
            conf = float(conf_val)
        out.append(ProVlmBoundingBox(label=label, bbox=bbox, confidence=conf))
    return out


def _coerce_bbox(v: Any) -> list[float] | None:
    if not isinstance(v, list) or len(v) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    except Exception:
        return None
    # Clamp to 0..1
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    x2 = max(0.0, min(1.0, x2))
    y2 = max(0.0, min(1.0, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]

