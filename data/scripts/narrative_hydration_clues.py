"""
Street View + satellite text for narrative LLM prompts (no torch / no httpx).

``narrative_llm_batch.py`` substitutes ``{{streetview_clue}}`` and ``{{satellite_clue}}`` from
``data/cache/<cv>/streetview/<location_id>.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


def _truncate_at_boundary(text: str, max_chars: int) -> str:
    """Prefer sentence or word boundary before ``max_chars``; append ellipsis when trimmed."""
    t = text.strip()
    if max_chars < 32 or len(t) <= max_chars:
        return t if len(t) <= max_chars else t[:max_chars].rstrip()
    window = t[:max_chars]
    cut = max(
        window.rfind(". "),
        window.rfind(".\n"),
        window.rfind("? "),
        window.rfind("! "),
        window.rfind("\n\n"),
    )
    if cut < max_chars // 3:
        sp = window.rfind(" ")
        cut = sp if sp > max_chars // 3 else max_chars - 1
    out = t[: cut + 1].strip() if cut >= 0 else window.strip()
    if len(out) < len(t):
        out = out.rstrip(".,; ") + "…"
    return out


def _excerpt_sentences(text: str, max_chars: int, max_sentences: int = 4) -> str:
    """Take leading sentences until char budget; then boundary-truncate."""
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) <= max_chars:
        return t
    parts = re.split(r"(?<=[.!?])\s+", t)
    out_parts: list[str] = []
    n = 0
    for p in parts:
        if not p:
            continue
        cand = (" ".join(out_parts + [p])).strip()
        if len(cand) > max_chars or n >= max_sentences:
            break
        out_parts.append(p)
        n += 1
    if not out_parts:
        return _truncate_at_boundary(t, max_chars)
    joined = " ".join(out_parts).strip()
    return _truncate_at_boundary(joined, max_chars) if len(joined) > max_chars else joined


def _apply_clue_budget(raw: str, budget: int | None) -> str:
    if budget is None or budget <= 0:
        return raw
    if len(raw) <= budget:
        return raw
    return _excerpt_sentences(raw, budget)


def hydration_clues_for_narrative_prompt(
    doc: Mapping[str, Any] | None,
    *,
    street_budget: int | None = None,
    sat_budget: int | None = None,
) -> tuple[str, str]:
    """
    One street-level line + one satellite line for ``prompts/llm/*.md`` substitution.

    Street: prefer ``streetview_assist_narrative``; else first non-empty ``streetview_hint_pack[].text``.
    Satellite: ``satellite_caption_sidecar.caption`` when present.
    """
    if not doc:
        return (
            "(No streetview hydration document; write generic tone only.)",
            "(No satellite caption; keep overhead imagery vague.)",
        )
    nar = doc.get("streetview_assist_narrative")
    if isinstance(nar, str) and nar.strip():
        street = nar.strip()
    else:
        street = ""
        pack = doc.get("streetview_hint_pack")
        if isinstance(pack, list):
            for item in pack:
                if isinstance(item, dict):
                    t = str(item.get("text", "")).strip()
                    if t:
                        street = t
                        break
    if not street:
        street = "(No street-level caption text in hydration; infer mood only, no invented landmarks.)"

    sat = ""
    sc = doc.get("satellite_caption_sidecar")
    if isinstance(sc, dict):
        cap = sc.get("caption")
        if isinstance(cap, str) and cap.strip():
            sat = cap.strip()
    if not sat:
        sat = "(No satellite caption in hydration; do not invent overhead detail.)"

    street = _apply_clue_budget(street, street_budget)
    sat = _apply_clue_budget(sat, sat_budget)
    return street, sat


def load_streetview_hydration_doc(cache_root: Path, location_id: str) -> Mapping[str, Any] | None:
    p = cache_root / "streetview" / f"{location_id}.json"
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None
