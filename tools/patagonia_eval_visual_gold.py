"""Per-AOI labelled visual gold (YAML) for Patagonia eval.

This complements automatic SCL-derived ``gold_boxes`` by attaching *human-authored*
metadata such as ``no_local_features: true`` for open-ocean tiles where IoU against
SCL components is meaningless.

YAML layout (``tools/data/patagonia_visual_gold.yaml``)::

    targets:
      pat_namuncura_burdwood:
        no_local_features: true
        notes: "Open ocean MPA; no discrete SCL components to localize."
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_VISUAL_GOLD_YAML = Path(__file__).resolve().parent / "data" / "patagonia_visual_gold.yaml"


def load_visual_gold(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_VISUAL_GOLD_YAML
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    tgts = raw.get("targets")
    if not isinstance(tgts, dict):
        return {}
    return {str(k): v for k, v in tgts.items() if isinstance(v, dict)}


def has_no_local_features(target_id: str, *, gold: dict[str, Any] | None = None) -> bool:
    g = gold if gold is not None else load_visual_gold()
    entry = g.get(target_id) or {}
    return bool(entry.get("no_local_features"))


def gold_meta_for_target(target_id: str, *, gold: dict[str, Any] | None = None) -> dict[str, Any]:
    g = gold if gold is not None else load_visual_gold()
    return dict(g.get(target_id) or {})
