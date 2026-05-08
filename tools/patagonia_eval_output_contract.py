"""Hard output-contract scorer for Patagonia VLM eval.

Validates the SFT-trained ``production_analysis`` output contract:

- A free-text caption preamble (≥ ``min_words`` whitespace tokens).
- A single trailing ```json``` fenced block.
- The fenced block parses to ``{"boxes": [{label, bbox:[x1,y1,x2,y2]∈[0,1], confidence∈[0,1]}, ...]}``.
- No prompt-marker leaks (``[captions:``, ``[boxes]``, literal ``x1=0.0``, etc.).

This module replaces the soft, four-check ``structured_task_score`` floor (which left
~73% of rows at score 1.0 and could not surface formatting regressions like the
``finetune`` checkpoint emitting ``[x1=0.0,y1=0.0,...]`` literals).
"""

from __future__ import annotations

import json
import re
from typing import Any


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)```", re.IGNORECASE)
_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("captions_marker", re.compile(r"\[captions?\s*:", re.IGNORECASE)),
    ("boxes_marker", re.compile(r"\[boxes\]", re.IGNORECASE)),
    ("xy_eq_zero_literal", re.compile(r"\bx1\s*=\s*0\.0\s*,\s*y1\s*=\s*0\.0", re.IGNORECASE)),
    (
        "tim_style_analytics_label",
        re.compile(r"tim[-\s]style\s+analytics\s+json\s*:?", re.IGNORECASE),
    ),
    ("image_sequence_echo", re.compile(r"^\s*-\s*image\s+sequence\s*:", re.IGNORECASE | re.MULTILINE)),
)


def _extract_trailing_fenced_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return parsed dict from the *last* ```json``` fenced block, or ``(None, error_code)``."""
    matches = list(_FENCED_JSON_RE.finditer(text or ""))
    if not matches:
        return None, "no_fenced_block"
    last = matches[-1].group(1).strip()
    if not last.startswith("{"):
        return None, "fenced_block_not_object"
    try:
        obj = json.loads(last)
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error:{exc.msg}"
    if not isinstance(obj, dict):
        return None, "fenced_block_not_object"
    return obj, None


def _validate_boxes_v1(obj: dict[str, Any]) -> tuple[bool, str | None, int]:
    """Return ``(ok, error_code, n_boxes)``. ``boxes`` may be empty (proper abstention)."""
    arr = obj.get("boxes")
    if arr is None:
        return False, "missing_boxes_key", 0
    if not isinstance(arr, list):
        return False, "boxes_not_list", 0
    if not arr:
        return True, None, 0
    for i, item in enumerate(arr):
        if not isinstance(item, dict):
            return False, f"box_{i}_not_object", len(arr)
        bb = item.get("bbox")
        if not isinstance(bb, list) or len(bb) != 4:
            return False, f"box_{i}_bbox_shape", len(arr)
        try:
            x1, y1, x2, y2 = (float(c) for c in bb)
        except (TypeError, ValueError):
            return False, f"box_{i}_bbox_numeric", len(arr)
        if not all(0.0 <= c <= 1.0 for c in (x1, y1, x2, y2)):
            return False, f"box_{i}_bbox_range", len(arr)
        if not (x1 < x2 and y1 < y2):
            return False, f"box_{i}_bbox_order", len(arr)
        cf = item.get("confidence")
        if cf is not None:
            if not isinstance(cf, (int, float)):
                return False, f"box_{i}_confidence_type", len(arr)
            if not (0.0 <= float(cf) <= 1.0):
                return False, f"box_{i}_confidence_range", len(arr)
    return True, None, len(arr)


def _marker_leaks(text: str) -> list[str]:
    return [name for name, pat in _LEAK_PATTERNS if pat.search(text or "")]


def _caption_preamble_words(text: str) -> int:
    """Word count of the text *before* the last fenced block (approx caption preamble length)."""
    matches = list(_FENCED_JSON_RE.finditer(text or ""))
    if matches:
        head = (text or "")[: matches[-1].start()]
    else:
        head = text or ""
    head = head.strip()
    if not head:
        return 0
    return len([w for w in re.split(r"\s+", head) if w])


def output_contract_score(
    caption: str,
    *,
    min_caption_words: int = 12,
    require_boxes_when_no_local_features: bool = False,
) -> tuple[float, dict[str, Any]]:
    """Return ``(score in [0,1], breakdown)`` for the production-analysis output contract.

    Scoring ladder (highest match wins, leaks always force 0.0):

    - Any prompt-marker leak                                      → 0.00
    - No fenced JSON at all                                       → 0.00
    - Fenced JSON unparseable                                     → 0.40
    - Parseable but wrong schema                                  → 0.60
    - Schema valid but caption preamble is too short              → 0.80
    - Schema valid + caption ≥ ``min_caption_words``              → 1.00
    """
    text = caption or ""
    leaks = _marker_leaks(text)
    obj, parse_error = _extract_trailing_fenced_json(text)
    schema_ok, schema_error, n_boxes = (False, "no_object", 0) if obj is None else _validate_boxes_v1(obj)
    preamble_words = _caption_preamble_words(text)

    breakdown: dict[str, Any] = {
        "leaks": leaks,
        "has_fenced_json": obj is not None or (parse_error is not None and parse_error != "no_fenced_block"),
        "json_parse_error": parse_error,
        "schema_ok": schema_ok,
        "schema_error": schema_error,
        "n_boxes": n_boxes,
        "preamble_words": preamble_words,
        "min_caption_words": min_caption_words,
        "require_boxes_when_no_local_features": require_boxes_when_no_local_features,
    }

    if leaks:
        return 0.0, {**breakdown, "verdict": "leak"}
    if obj is None and parse_error == "no_fenced_block":
        return 0.0, {**breakdown, "verdict": "no_fenced_block"}
    if obj is None:
        return 0.4, {**breakdown, "verdict": "json_parse_failed"}
    if not schema_ok:
        return 0.6, {**breakdown, "verdict": "schema_invalid"}
    if preamble_words < min_caption_words:
        return 0.8, {**breakdown, "verdict": "preamble_too_short"}
    return 1.0, {**breakdown, "verdict": "ok"}
