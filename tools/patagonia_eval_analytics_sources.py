"""Analytics-source axis for Patagonia VLM eval (decouples model eval from TerraMind TiM).

Sources:
- ``none``               — image-only baseline (no analytics JSON injected).
- ``procedural``         — deterministic SFT-procedural analytics built from per-target
                           Sentinel-2 SCL fractions (matches the SFT training distribution
                           via ``data/scripts/lfm_vl_sft_dataset/sat_bbox_metadata_sft.py``).
- ``synthetic_oracle``   — hand-curated per-AOI fractions from
                           ``tools/data/patagonia_synthetic_oracle.yaml``; same shape as
                           ``procedural`` but with known-correct fractions (for faithfulness
                           upper-bound testing).
- ``tim_generated``      — current TerraMind TiM compact JSON. Routed through the TiM
                           health gate; if ``tim_health=="degenerate"`` and source is
                           ``procedural_or_tim`` we fall back to ``procedural``.
- ``procedural_or_tim``  — prefer ``tim_generated`` when healthy, else ``procedural``.
- ``dynamic_world``      — analytics fractions from **Google Dynamic World** (Earth Engine) when
                           ``gold/<id>.json`` contains ``dynamic_world_fractions``; else SCL procedural
                           (``dynamic_world_fallback_scl``).
- ``procedural_or_dw``   — prefer healthy TiM, else Dynamic World fractions when present, else SCL procedural.

The compact JSON shape is identical across sources (``tim_modality_outputs`` +
``profile_analytics``); only provenance changes. Faithfulness scoring is source-agnostic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_SCRIPTS = REPO_ROOT / "data" / "scripts"
if str(_DATA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_DATA_SCRIPTS))

from lfm_vl_sft_dataset.instances import DYNAMIC_WORLD_CLASSES  # noqa: E402
from lfm_vl_sft_dataset.sat_bbox_metadata_sft import (  # noqa: E402
    build_procedural_tim_context,
    procedural_tim_fractions,
    tim_context_for_user_prompt,
)


AnalyticsSource = Literal[
    "none",
    "procedural",
    "dynamic_world",
    "synthetic_oracle",
    "tim_generated",
    "procedural_or_tim",
    "procedural_or_dw",
]
ALL_SOURCES: tuple[AnalyticsSource, ...] = (
    "none",
    "procedural",
    "dynamic_world",
    "synthetic_oracle",
    "tim_generated",
    "procedural_or_tim",
    "procedural_or_dw",
)


# ESA SCL → Dynamic World 9-class mapping (best-effort coarse roll-up).
# SCL: 0=NoData, 1=Saturated, 2=Topo shadow, 3=Cloud shadow, 4=Vegetation, 5=Bare,
# 6=Water, 7=Cloud low prob, 8=Cloud med, 9=Cloud high, 10=Cirrus, 11=Snow/Ice.
_SCL_TO_DW: dict[int, int] = {
    4: 1,   # Vegetation → trees (coarse; finer split would need Dynamic World directly)
    5: 7,   # Bare → bare_ground
    6: 0,   # Water
    11: 8,  # Snow/Ice → snow_and_ice
}
_SCL_VALID_DATA = (4, 5, 6, 11)

# When cloud cover dominates, strict SCL→DW fractions can be empty (no class in 4,5,6,11).
# Open-ocean / offshore AOIs still need a weak prior for procedural analytics + faithfulness.
_MARINE_OPEN_WATER_CATEGORIES: frozenset[str] = frozenset(
    {
        "marine_reserve",
        "marine_reserve_offshore",
        "marine_reserve_nearshore",
        "marine_reserve_coastal",
        "marine_reserve_nearshore_control",
    }
)


DEFAULT_SYNTHETIC_ORACLE_YAML = REPO_ROOT / "tools" / "data" / "patagonia_synthetic_oracle.yaml"


def sentinel_fractions_from_scl(scl_chip_uint8: np.ndarray) -> dict[int, float]:
    """Collapse an SCL chip to Dynamic World class-id fractions over valid pixels.

    Pixels in clouds / shadows / no-data are excluded. If no valid pixels exist, returns
    an empty dict (caller should fall back to ``synthetic_oracle`` or skip the row).
    """
    if scl_chip_uint8.size == 0:
        return {}
    flat = scl_chip_uint8.ravel().astype(np.int64)
    valid_mask = np.isin(flat, np.array(_SCL_VALID_DATA, dtype=np.int64))
    valid = flat[valid_mask]
    n = int(valid.size)
    if n <= 0:
        return {}
    out: dict[int, float] = {}
    for scl_v, dw_id in _SCL_TO_DW.items():
        cnt = int(np.sum(valid == scl_v))
        if cnt > 0:
            out[dw_id] = out.get(dw_id, 0.0) + float(cnt) / float(n)
    return {cid: round(frac, 6) for cid, frac in out.items() if frac > 0}


def sentinel_fractions_for_patagonia_chip(
    scl_chip_uint8: np.ndarray,
    *,
    category: str,
) -> tuple[dict[int, float], str]:
    """Strict SCL collapse; if empty and category is open-water marine, use 100% DW **water** (id 0).

    Returns ``(fractions, tag)`` where ``tag`` is ``strict``, ``marine_water_prior``, or ``empty``.
    """
    fr = sentinel_fractions_from_scl(scl_chip_uint8)
    if fr:
        return fr, "strict"
    cat = (category or "").strip().lower()
    if cat in _MARINE_OPEN_WATER_CATEGORIES:
        return {0: 1.0}, "marine_water_prior"
    return {}, "empty"


def fractions_from_dynamic_world_label(label_chip_uint8: np.ndarray) -> dict[int, float]:
    """Direct Dynamic World ``label`` chip → class-id fractions (already in DW space)."""
    flat = label_chip_uint8.ravel().astype(np.int64)
    valid = flat[(flat >= 0) & (flat < 9)]
    n = int(valid.size)
    if n <= 0:
        return {}
    out: dict[int, float] = {}
    for cid in DYNAMIC_WORLD_CLASSES:
        cnt = int(np.sum(valid == cid))
        if cnt > 0:
            out[cid] = round(float(cnt) / float(n), 6)
    return out


def _normalize(fractions: dict[int, float]) -> dict[int, float]:
    total = sum(max(0.0, float(v)) for v in fractions.values())
    if total <= 0:
        return {}
    return {cid: round(max(0.0, float(v)) / total, 6) for cid, v in fractions.items() if v > 0}


def build_procedural_analytics(
    *,
    target_id: str,
    profile: str,
    sentinel_fractions: dict[int, float],
    scene_meta: dict[str, Any] | None = None,
    target_lat: float | None = None,
    target_lon: float | None = None,
    tim_fractions: dict[int, float] | None = None,
    profile_analytics_source: str | None = None,
) -> dict[str, Any]:
    """Build a compact procedural TiM-shape JSON aligned with SFT training prompts.

    Returns ``{"tim_modality_outputs": ..., "profile_analytics": ..., "inputs_meta": ...}``
    with provenance tags so the report can attribute the source to ``procedural``.
    """
    fr = _normalize(sentinel_fractions)
    if not fr:
        return {
            "tim_modality_outputs": {},
            "profile_analytics": {"profile": profile, "source": "procedural_empty"},
            "inputs_meta": {"reason": "no_valid_scl_pixels"},
        }
    meta_in: dict[str, Any] = dict(scene_meta or {})
    if target_lat is not None and "latitude" not in meta_in:
        meta_in["latitude"] = float(target_lat)
    if target_lon is not None and "longitude" not in meta_in:
        meta_in["longitude"] = float(target_lon)

    tim_fr = tim_fractions if tim_fractions is not None else procedural_tim_fractions(fr, profile=profile)
    ctx = build_procedural_tim_context(
        meta=meta_in,
        sentinel_fractions=fr,
        profile=profile,
        tim_fractions=tim_fr,
    )
    pa = ctx.get("profile_analytics") or {}
    if isinstance(pa, dict):
        pa["target_id"] = target_id
        pa.setdefault("source", "procedural")
        if profile_analytics_source:
            pa["source"] = profile_analytics_source
    ctx["profile_analytics"] = pa
    return ctx


def trim_for_prompt(analytics: dict[str, Any]) -> dict[str, Any]:
    """Apply the SFT prompt trim (``inputs_meta``, ``scene_provenance``, etc. removed)."""
    return tim_context_for_user_prompt(analytics)


def load_synthetic_oracle(path: Path = DEFAULT_SYNTHETIC_ORACLE_YAML) -> dict[str, dict[str, Any]]:
    """Read per-target oracle entries; return ``{}`` if the YAML is missing."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for tid, entry in raw.items():
        if isinstance(entry, dict):
            out[str(tid)] = entry
    return out


def build_synthetic_oracle_analytics(
    *,
    target_id: str,
    profile: str,
    target_lat: float,
    target_lon: float,
    oracle: dict[str, dict[str, Any]] | None = None,
    oracle_path: Path = DEFAULT_SYNTHETIC_ORACLE_YAML,
) -> dict[str, Any] | None:
    """Build oracle analytics from the curated YAML; returns ``None`` if entry missing."""
    src = oracle if oracle is not None else load_synthetic_oracle(oracle_path)
    entry = src.get(target_id)
    if not entry:
        return None
    raw = entry.get("sentinel_fractions") or {}
    fr_named: dict[str, float] = {str(k): float(v) for k, v in raw.items()}
    name_to_id = {name: cid for cid, name in DYNAMIC_WORLD_CLASSES.items()}
    fractions = {name_to_id[k]: v for k, v in fr_named.items() if k in name_to_id and v > 0}
    if not fractions:
        return None
    ctx = build_procedural_analytics(
        target_id=target_id,
        profile=profile,
        sentinel_fractions=fractions,
        target_lat=target_lat,
        target_lon=target_lon,
    )
    pa = ctx.get("profile_analytics") or {}
    if isinstance(pa, dict):
        pa["source"] = "synthetic_oracle"
    ctx["profile_analytics"] = pa
    return ctx


def select_analytics(
    source: AnalyticsSource,
    *,
    target_id: str,
    profile: str,
    target_lat: float,
    target_lon: float,
    sentinel_fractions: dict[int, float] | None,
    dynamic_world_fractions: dict[int, float] | None = None,
    scene_meta: dict[str, Any] | None,
    tim_compact: dict[str, Any] | None,
    tim_health: str | None,
    oracle: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve which analytics JSON to inject. Returns ``(analytics, resolved_source)``.

    ``resolved_source`` is the *concrete* source label (e.g. ``procedural_after_tim_degenerate``)
    that goes into the report row for downstream stratification.
    """
    if source == "none":
        return None, "none"

    if source == "synthetic_oracle":
        out = build_synthetic_oracle_analytics(
            target_id=target_id,
            profile=profile,
            target_lat=target_lat,
            target_lon=target_lon,
            oracle=oracle,
        )
        if out is None:
            return None, "synthetic_oracle_missing"
        return out, "synthetic_oracle"

    if source == "tim_generated":
        if tim_compact and tim_health == "good":
            return tim_compact, "tim_generated"
        return tim_compact if tim_compact else None, f"tim_generated_health={tim_health or 'unknown'}"

    if source == "procedural_or_tim":
        if tim_compact and tim_health == "good":
            return tim_compact, "tim_generated"
        # fall through to procedural
        if sentinel_fractions:
            built = build_procedural_analytics(
                target_id=target_id,
                profile=profile,
                sentinel_fractions=sentinel_fractions,
                scene_meta=scene_meta,
                target_lat=target_lat,
                target_lon=target_lon,
            )
            return built, f"procedural_fallback_tim_health={tim_health or 'unknown'}"
        return None, "procedural_or_tim_no_inputs"

    if source == "procedural_or_dw":
        if tim_compact and tim_health == "good":
            return tim_compact, "tim_generated"
        dw_fr = _normalize(dynamic_world_fractions or {})
        if dw_fr:
            return (
                build_procedural_analytics(
                    target_id=target_id,
                    profile=profile,
                    sentinel_fractions=dw_fr,
                    scene_meta=scene_meta,
                    target_lat=target_lat,
                    target_lon=target_lon,
                    profile_analytics_source="dynamic_world",
                ),
                "procedural_or_dw_dynamic_world",
            )
        if sentinel_fractions:
            return (
                build_procedural_analytics(
                    target_id=target_id,
                    profile=profile,
                    sentinel_fractions=sentinel_fractions,
                    scene_meta=scene_meta,
                    target_lat=target_lat,
                    target_lon=target_lon,
                ),
                "procedural_or_dw_scl",
            )
        return None, "procedural_or_dw_no_inputs"

    if source == "dynamic_world":
        dw_fr = _normalize(dynamic_world_fractions or {})
        if dw_fr:
            return (
                build_procedural_analytics(
                    target_id=target_id,
                    profile=profile,
                    sentinel_fractions=dw_fr,
                    scene_meta=scene_meta,
                    target_lat=target_lat,
                    target_lon=target_lon,
                    profile_analytics_source="dynamic_world",
                ),
                "dynamic_world",
            )
        if sentinel_fractions:
            return (
                build_procedural_analytics(
                    target_id=target_id,
                    profile=profile,
                    sentinel_fractions=sentinel_fractions,
                    scene_meta=scene_meta,
                    target_lat=target_lat,
                    target_lon=target_lon,
                ),
                "dynamic_world_fallback_scl",
            )
        return None, "dynamic_world_no_inputs"

    if source == "procedural":
        if not sentinel_fractions:
            return None, "procedural_no_scl_fractions"
        return (
            build_procedural_analytics(
                target_id=target_id,
                profile=profile,
                sentinel_fractions=sentinel_fractions,
                scene_meta=scene_meta,
                target_lat=target_lat,
                target_lon=target_lon,
            ),
            "procedural",
        )

    return None, f"unknown_source:{source}"
