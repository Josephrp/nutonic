"""Metadata-first procedural SFT rows for ``sat-image-boundingbox-sft-full``-style datasets.

Reads ``data/<split>.jsonl`` for stable relative image paths, ``metadata/s*/**.json`` for
labels (caption, regions, class_fractions), and optionally pairs existing ``mapbox_stills/``
paths. Does **not** call Mapbox APIs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from PIL import Image

from lfm_vl_sft_dataset.instances import DYNAMIC_WORLD_CLASSES, RegionAnn, regions_to_normalized_json
from lfm_vl_sft_dataset.jsonl_format import (
    MAPBOX_OVERVIEW_PROMPT,
    caption_row,
    class_focus_caption_row,
    grounding_row,
    make_multi_image_vlm_message,
    split_key,
)
from lfm_vl_sft_dataset.pro_prompts import SYSTEM_GEOSPATIAL_ANALYST, SYSTEM_OPTICAL_LIMITS

# Substrings that must never appear in training prompts / answers (TiM / export bloat).
BANNED_TRAINING_SUBSTRINGS: tuple[str, ...] = (
    "_inputs",
    "_internal_coords",
    "npz_base64",
    "inline_base64",
    "decoder_attention_mask",
    "engine.patch_diagnostics",
)

_STEM_TILE_SUFFIX = re.compile(r"_t\d{4,}$")
_BASE_POI_RE = re.compile(r"^(poi_\d+)")

PRODUCTION_ANALYSIS_PROFILES: tuple[str, ...] = (
    "brief_only",
    "land_use_change",
    "wildfire",
    "flood_pulse",
    "oceanscout_ship_detection",
)


def normalize_production_analysis_profile(profile: str) -> str:
    """Map legacy API tokens to production profile names (see server ``normalize_analysis_profile``)."""
    p = profile.strip()
    if p == "vessel_monitoring":
        return "oceanscout_ship_detection"
    return p


# Keep in sync with ``nutonic_terramind_tim_local.oceanscout_policy.OCEANSCOUT_SHORELINE_POLICY``.
PROCEDURAL_OCEANSCOUT_SHORELINE_POLICY: dict[str, float | str] = {
    "version": "1.0",
    "buffer_m": 500.0,
    "morphology_kernel_px": 3.0,
    "min_water_fraction": 0.3,
}

PRODUCTION_ANALYSIS_SYSTEM = (
    f"{SYSTEM_GEOSPATIAL_ANALYST} {SYSTEM_OPTICAL_LIMITS} "
    "You receive Sentinel-2 imagery plus a compact TiM-style analytics JSON block (model-shaped signals). "
    "Write an analytical summary grounded in the images and that JSON; distinguish what you infer from "
    "the optical chip from TiM-predicted signals encoded in the JSON."
)

LAND_COVER_RGB: dict[str, tuple[int, int, int]] = {
    "water": (45, 115, 210),
    "trees": (36, 130, 70),
    "grass": (128, 190, 80),
    "flooded_vegetation": (75, 170, 160),
    "crops": (218, 190, 82),
    "shrub_and_scrub": (142, 150, 76),
    "built": (210, 76, 70),
    "bare_ground": (168, 145, 110),
    "snow_and_ice": (236, 242, 248),
}


def base_poi_id_from_stem(tile_stem: str) -> str:
    m = _BASE_POI_RE.match(tile_stem.strip())
    return m.group(1) if m else tile_stem


def mapbox_lookup_stem(satellite_tile_stem: str) -> str:
    """``poi_000099_g001_t0000`` → ``poi_000099_g001`` (strip trailing ``_tNNNN``)."""
    s = satellite_tile_stem.strip()
    return _STEM_TILE_SUFFIX.sub("", s)


def iter_dataset_jsonl_files(dataset_root: Path, *, split: str) -> list[Path]:
    data_dir = dataset_root / "data"
    if not data_dir.is_dir():
        return []
    if split == "all":
        names = ("train.jsonl", "validation.jsonl", "test.jsonl")
        return [data_dir / n for n in names if (data_dir / n).is_file()]
    return [data_dir / f"{split}.jsonl"] if (data_dir / f"{split}.jsonl").is_file() else []


def _iter_image_refs_from_jsonl_line(obj: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield ``(rel_path, modality)`` for image parts; modality is ``images`` or ``mapbox``."""
    msgs = obj.get("messages")
    if not isinstance(msgs, list):
        return
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image":
                continue
            rel = part.get("image")
            if not isinstance(rel, str) or not rel.strip():
                continue
            rel = rel.strip().replace("\\", "/")
            if rel.startswith("images/"):
                yield rel, "images"
            elif rel.startswith("mapbox_stills/"):
                yield rel, "mapbox"


def index_jsonl_image_paths(jsonl_paths: Iterable[Path]) -> tuple[dict[str, str], dict[str, str]]:
    """Build stem → rel path indexes for satellite and mapbox stills."""
    sat: dict[str, str] = {}
    mb: dict[str, str] = {}
    for jp in jsonl_paths:
        if not jp.is_file():
            continue
        for line in jp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rel, kind in _iter_image_refs_from_jsonl_line(obj):
                stem = Path(rel).stem
                if kind == "images":
                    sat.setdefault(stem, rel)
                else:
                    mb.setdefault(stem, rel)
    return sat, mb


def discover_metadata_paths(dataset_root: Path) -> list[Path]:
    meta_root = dataset_root / "metadata"
    if not meta_root.is_dir():
        return []
    return sorted(p for p in meta_root.rglob("*.json") if p.is_file())


def _sidecar_split(meta: dict[str, Any], *, tile_stem: str) -> str:
    s = meta.get("split")
    if isinstance(s, str) and s.strip().lower() in ("train", "validation", "test"):
        return s.strip().lower()
    pid = meta.get("poi_id")
    if isinstance(pid, str) and pid.strip():
        return split_key(pid.strip())
    return split_key(base_poi_id_from_stem(tile_stem))


def _parse_bbox_wgs84(bb: Any) -> dict[str, float] | None:
    if isinstance(bb, dict):
        w, s_, e, n = bb.get("west"), bb.get("south"), bb.get("east"), bb.get("north")
        if all(isinstance(x, (int, float)) for x in (w, s_, e, n)):
            return {"west": float(w), "south": float(s_), "east": float(e), "north": float(n)}
        return None
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        w, s_, e, n = bb
        if all(isinstance(x, (int, float)) for x in (w, s_, e, n)):
            return {"west": float(w), "south": float(s_), "east": float(e), "north": float(n)}
    return None


def collect_split_leakage_bases(metadata_paths: Iterable[Path]) -> set[str]:
    """Return base POI ids that appear under more than one train/val/test split in metadata."""
    base_to_splits: dict[str, set[str]] = {}
    for p in metadata_paths:
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        stem = str(meta.get("tile_stem") or p.stem).strip()
        sp = _sidecar_split(meta, tile_stem=stem)
        b = base_poi_id_from_stem(stem)
        base_to_splits.setdefault(b, set()).add(sp)
    leaked: set[str] = set()
    for b, splits in base_to_splits.items():
        if len(splits) > 1:
            leaked.add(b)
    return leaked


def regions_from_sidecar(
    regions_raw: Any,
    *,
    image_w: int,
    image_h: int,
) -> list[RegionAnn]:
    out: list[RegionAnn] = []
    if not isinstance(regions_raw, list):
        return out
    for r in regions_raw:
        if not isinstance(r, dict):
            continue
        bb = r.get("bbox")
        if not isinstance(bb, (list, tuple)) or len(bb) != 4:
            continue
        x1, y1, x2, y2 = (int(round(float(x))) for x in bb)
        lab = str(r.get("label") or "").strip()
        cid = r.get("class_id")
        if not isinstance(cid, int):
            try:
                cid = int(cid)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        apx = r.get("area_px")
        if isinstance(apx, (int, float)):
            area_px = int(apx)
        else:
            area_px = max(0, (x2 - x1) * (y2 - y1))
        if not lab or cid not in DYNAMIC_WORLD_CLASSES:
            continue
        out.append(RegionAnn(bbox_xyxy=(x1, y1, x2, y2), label=lab, class_id=cid, area_px=area_px))
    # clip to image bounds
    clipped: list[RegionAnn] = []
    for r in out:
        x1, y1, x2, y2 = r.bbox_xyxy
        x1c = max(0, min(image_w, x1))
        y1c = max(0, min(image_h, y1))
        x2c = max(0, min(image_w, x2))
        y2c = max(0, min(image_h, y2))
        if x2c <= x1c or y2c <= y1c:
            continue
        clipped.append(
            RegionAnn(
                bbox_xyxy=(x1c, y1c, x2c, y2c),
                label=r.label,
                class_id=r.class_id,
                area_px=r.area_px,
            )
        )
    return clipped


def parse_class_fractions(raw: Any) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            cid = int(k)
        except (TypeError, ValueError):
            continue
        if cid not in DYNAMIC_WORLD_CLASSES:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out[cid] = fv
    return out


def normalize_fractions(fractions: dict[int, float]) -> dict[int, float]:
    clipped = {cid: max(0.0, float(v)) for cid, v in fractions.items() if cid in DYNAMIC_WORLD_CLASSES}
    total = sum(clipped.values())
    if total <= 0:
        return {}
    return {cid: round(v / total, 6) for cid, v in clipped.items() if v > 0}


def class_fraction_sample(fractions: dict[int, float], *, sample_count: int = 32) -> list[float]:
    """Compact class-id sample analogous to TiM ``classes.sample`` arrays."""
    norm = normalize_fractions(fractions)
    if not norm:
        return []
    counts: list[tuple[int, int]] = []
    used = 0
    ordered = sorted(norm.items(), key=lambda kv: kv[1], reverse=True)
    for cid, frac in ordered:
        count = max(1, int(round(frac * sample_count)))
        counts.append((cid, count))
        used += count
    if used > sample_count:
        overflow = used - sample_count
        counts[-1] = (counts[-1][0], max(1, counts[-1][1] - overflow))
    elif used < sample_count:
        cid0, c0 = counts[0]
        counts[0] = (cid0, c0 + (sample_count - used))
    sample: list[float] = []
    for cid, count in counts:
        sample.extend([float(cid)] * count)
    return sample[:sample_count]


def _shift_fraction(
    fractions: dict[int, float],
    *,
    increase: dict[int, float],
    decrease_order: tuple[int, ...],
) -> dict[int, float]:
    out = dict(normalize_fractions(fractions))
    for cid, delta in increase.items():
        out[cid] = out.get(cid, 0.0) + delta
        remaining = delta
        for src in decrease_order:
            if remaining <= 0:
                break
            take = min(out.get(src, 0.0), remaining)
            if take > 0:
                out[src] = out.get(src, 0.0) - take
                remaining -= take
    return normalize_fractions(out)


def procedural_tim_fractions(
    sentinel_fractions: dict[int, float],
    *,
    profile: str,
) -> dict[int, float]:
    """Create TiM-like predicted fractions from metadata without calling TiM."""
    base = normalize_fractions(sentinel_fractions)
    if profile == "land_use_change":
        return _shift_fraction(base, increase={6: 0.12}, decrease_order=(1, 2, 5, 7, 4, 0, 8))
    if profile == "wildfire":
        return _shift_fraction(base, increase={7: 0.10}, decrease_order=(1, 5, 2, 4, 6, 0, 8))
    if profile == "flood_pulse":
        return _shift_fraction(base, increase={0: 0.15}, decrease_order=(2, 4, 5, 7, 6, 1, 8))
    if profile == "oceanscout_ship_detection":
        return _shift_fraction(base, increase={0: 0.06}, decrease_order=(7, 2, 5, 6, 1, 4, 8))
    return base


def _named_fraction_map(fractions: dict[int, float]) -> dict[str, float]:
    return {
        DYNAMIC_WORLD_CLASSES[cid]: round(frac, 6)
        for cid, frac in sorted(normalize_fractions(fractions).items())
    }


def dominant_classes(fractions: dict[int, float], *, limit: int = 4) -> list[dict[str, Any]]:
    return [
        {"class_id": cid, "label": DYNAMIC_WORLD_CLASSES[cid], "fraction": round(frac, 6)}
        for cid, frac in sorted(normalize_fractions(fractions).items(), key=lambda kv: kv[1], reverse=True)[
            :limit
        ]
    ]


def fraction_deltas(
    sentinel_fractions: dict[int, float],
    tim_fractions: dict[int, float],
) -> list[dict[str, Any]]:
    ids = sorted(set(sentinel_fractions) | set(tim_fractions))
    rows: list[dict[str, Any]] = []
    s_norm = normalize_fractions(sentinel_fractions)
    t_norm = normalize_fractions(tim_fractions)
    for cid in ids:
        if cid not in DYNAMIC_WORLD_CLASSES:
            continue
        before = s_norm.get(cid, 0.0)
        after = t_norm.get(cid, 0.0)
        delta = after - before
        if abs(delta) < 0.005:
            continue
        rows.append(
            {
                "class_id": cid,
                "label": DYNAMIC_WORLD_CLASSES[cid],
                "sentinel_fraction": round(before, 6),
                "tim_fraction": round(after, 6),
                "delta": round(delta, 6),
                "direction": "increase" if delta > 0 else "decrease",
            }
        )
    rows.sort(key=lambda r: abs(float(r["delta"])), reverse=True)
    return rows


def _pct_from_fraction(frac: float | None) -> str:
    if frac is None:
        return "unknown"
    return f"{round(frac * 100.0, 1)}%"


def build_procedural_tim_context(
    *,
    meta: dict[str, Any],
    sentinel_fractions: dict[int, float],
    profile: str,
    tim_fractions: dict[int, float] | None = None,
) -> dict[str, Any]:
    tim_fractions = tim_fractions or procedural_tim_fractions(sentinel_fractions, profile=profile)
    sample = class_fraction_sample(tim_fractions)
    coords: dict[str, Any] | None = None
    lat = meta.get("latitude")
    lon = meta.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        coords = {
            "kind": "coordinates_wgs84",
            "latitude": float(lat),
            "longitude": float(lon),
            "confidence": 0.9,
        }
    outputs: dict[str, Any] = {
        "LULC": {
            "internal_key": "tok_lulc@224",
            "kind": "class_logits",
            "shape": [224, 224],
            "class_fractions": _named_fraction_map(tim_fractions),
            "classes": {"sample": sample},
        },
        "tok_lulc@224": {
            "kind": "token_grid",
            "sample": sample,
            "shape": [224, 224],
        },
    }
    if coords is not None:
        outputs["Coordinates"] = coords
    inputs_meta = {
        "s2_stac": {
            "stac_item_id": meta.get("stac_item_id"),
            "stac_datetime": meta.get("stac_datetime") or meta.get("datetime"),
            "eo_cloud_cover": meta.get("eo_cloud_cover", 0.0),
        }
    }
    return {
        "tim_modality_outputs": outputs,
        "profile_analytics": build_procedural_profile_analytics(
            profile=profile,
            sentinel_fractions=sentinel_fractions,
            tim_fractions=tim_fractions,
            sample=sample,
            inputs_meta=inputs_meta,
        ),
        "inputs_meta": inputs_meta,
    }


def tim_context_for_user_prompt(tim_context: dict[str, Any]) -> dict[str, Any]:
    """TiM-shaped JSON for the model: drop STAC/sidecar echoes and Sentinel fraction repeats (see messages)."""
    tc = copy.deepcopy(tim_context)
    tc.pop("inputs_meta", None)
    pa = tc.get("profile_analytics")
    if isinstance(pa, dict):
        pa.pop("scene_provenance", None)
        summ = pa.get("summary")
        if isinstance(summ, dict):
            summ.pop("dominant_sentinel_classes", None)
            for row in summ.get("largest_deltas") or []:
                if isinstance(row, dict):
                    row.pop("sentinel_fraction", None)
        lt = pa.get("land_transition")
        if isinstance(lt, dict):
            for row in lt.get("top_transitions") or []:
                if isinstance(row, dict):
                    row.pop("sentinel_fraction", None)
    return tc


def _bins_from_deltas(deltas: list[dict[str, Any]]) -> dict[str, int]:
    bins = {"low": 0, "medium": 0, "high": 0}
    for row in deltas:
        magnitude = abs(float(row.get("delta", 0.0)))
        if magnitude >= 0.12:
            bins["high"] += 1
        elif magnitude >= 0.04:
            bins["medium"] += 1
        else:
            bins["low"] += 1
    return bins


def build_procedural_profile_analytics(
    *,
    profile: str,
    sentinel_fractions: dict[int, float],
    tim_fractions: dict[int, float],
    sample: list[float],
    inputs_meta: dict[str, Any],
) -> dict[str, Any]:
    deltas = fraction_deltas(sentinel_fractions, tim_fractions)
    base: dict[str, Any] = {
        "profile": profile,
        "schema_version": "1.0",
        "scene_provenance": inputs_meta.get("s2_stac"),
        "thresholds": {"schema_version": "1.0"},
    }
    bins = _bins_from_deltas(deltas)
    if profile == "land_use_change":
        base["land_transition"] = {
            "transition_matrix": [
                {
                    "from": row["label"],
                    "to": row["label"],
                    "count": int(round(abs(float(row["delta"])) * 1000)),
                    "pct": round(abs(float(row["delta"])) * 100.0, 3),
                    "direction": row["direction"],
                }
                for row in deltas[:8]
            ],
            "top_transitions": deltas[:8],
            "class_distribution": dominant_classes(tim_fractions),
            "raw_counts_total": len(sample),
            "normalized_total_pct": 100.0 if sample else 0.0,
            "temporal_comparison_available": True,
            "source_keys": ["Coordinates", "LULC", "tok_lulc@224"],
        }
    elif profile == "wildfire":
        affected = sum(max(0.0, float(row["delta"])) for row in deltas if row["label"] == "bare_ground")
        base["burn_change"] = {
            "changed_area_pct": round(affected * 100.0, 3),
            "hotspot_count": 1 if affected >= 0.04 else 0,
            "heat_clusters": [
                {
                    "cluster_id": "procedural-burn-0000",
                    "score": round(min(1.0, affected / 0.15), 6),
                    "confidence": "high" if affected >= 0.08 else "medium",
                    "source": "procedural_fraction_delta",
                }
            ]
            if affected > 0
            else [],
            "confidence_bins": bins,
            "source_keys": ["Coordinates", "LULC", "tok_lulc@224"],
            "sample_count": len(sample),
            "metric_source": "procedural_fraction_delta",
            "thresholds": {
                "normalized_signal_medium": 0.33,
                "normalized_signal_high": 0.67,
                "min_cluster_px": None,
            },
        }
    elif profile == "flood_pulse":
        water_delta = next((float(row["delta"]) for row in deltas if row["label"] == "water"), 0.0)
        expanded = max(0.0, water_delta)
        base["water_change"] = {
            "expanded_area_pct": round(expanded * 100.0, 3),
            "affected_area_proxy_pct": round(sum(abs(float(row["delta"])) for row in deltas) * 100.0, 3),
            "inundation_polygon_count": 1 if expanded >= 0.04 else 0,
            "confidence_bins": bins,
            "source_keys": ["Coordinates", "LULC", "tok_lulc@224"],
            "sample_count": len(sample),
            "metric_source": "procedural_fraction_delta",
            "thresholds": {"normalized_water_signal_high": 0.67, "min_polygon_area_m2": None},
        }
    elif profile == "oceanscout_ship_detection":
        water = normalize_fractions(tim_fractions).get(0, 0.0)
        candidate_signal = min(100.0, round(water * 30.0, 3))
        base["vessel_candidates"] = [
            {
                "candidate_id": "procedural-maritime-0000",
                "score": round(candidate_signal / 100.0, 6),
                "confidence": "medium",
                "evidence_level": "tim_pseudosar_plus_lulc",
                "claim_safety": "presence_indicator_not_legal_assertion",
            }
        ]
        base["observation_coverage"] = {
            "valid_observation_count": len(sample) if sample else None,
            "cloud_masked_count": 0,
            "glint_limited_count": None,
            "no_observation_count": 0 if sample else None,
            "normalization": "valid_observation_count",
        }
        base["detection_score_summary"] = {
            "sample_count": len(sample),
            "candidate_signal_pct": candidate_signal,
            "metric_source": "procedural_fraction_delta",
        }
        base["evidence_level"] = "tim_pseudosar_plus_lulc"
        base["confidence"] = {"method": "procedural_fraction_delta_v1", "bins": bins}
        base["notices"] = [
            "Candidate vessel detections are presence indicators and require corroboration.",
            "Pseudo-SAR-like TiM outputs are not equivalent to true SAR observations.",
        ]
        base["limitations"] = ["cloud", "sun_glint", "shoreline_ambiguity", "optical_only_constraints"]
        base["shoreline_policy"] = dict(PROCEDURAL_OCEANSCOUT_SHORELINE_POLICY)
    else:
        base["summary"] = {
            "kind": "brief_context",
            "dominant_sentinel_classes": dominant_classes(sentinel_fractions),
            "dominant_tim_classes": dominant_classes(tim_fractions),
            "largest_deltas": deltas[:5],
            "confidence": "procedural",
        }
    return base


def build_analytical_summary(
    *,
    profile: str,
    sentinel_fractions: dict[int, float],
    tim_context: dict[str, Any],
) -> str:
    tmo = tim_context["tim_modality_outputs"]
    tim_named = tmo["LULC"]["class_fractions"]
    tim_fractions = {
        cid: float(tim_named.get(name, 0.0))
        for cid, name in DYNAMIC_WORLD_CLASSES.items()
        if name in tim_named
    }
    deltas = fraction_deltas(sentinel_fractions, tim_fractions)
    preferred_label = {
        "land_use_change": "built",
        "wildfire": "bare_ground",
        "flood_pulse": "water",
        "oceanscout_ship_detection": "water",
    }.get(profile)
    largest = next((row for row in deltas if row["label"] == preferred_label), None)
    if largest is None and deltas:
        largest = deltas[0]
    sentinel_dom = dominant_classes(sentinel_fractions, limit=3)
    dom_text = ", ".join(
        f"{row['label']} ({_pct_from_fraction(float(row['fraction']))})" for row in sentinel_dom
    )
    lines = [
        "Analytical summary:",
        f"- Application profile: {profile}.",
        f"- Sentinel-2 observation: dominant classes are {dom_text or 'not available'}.",
    ]
    if largest is not None:
        noun = str(largest["label"]).replace("_", " ")
        lines.append(
            "- TiM comparison: "
            f"{noun} area is predicted to {largest['direction']} from "
            f"{_pct_from_fraction(float(largest['sentinel_fraction']))} to "
            f"{_pct_from_fraction(float(largest['tim_fraction']))}."
        )
    if profile == "land_use_change":
        built_delta = next((row for row in deltas if row["label"] == "built"), None)
        if built_delta is not None and built_delta["direction"] == "increase":
            lines.append("- Finding: the built area is predicted to increase relative to the optical-chip baseline.")
        else:
            lines.append("- Finding: no strong built-area expansion signal is present in this procedural TiM view.")
    elif profile == "wildfire":
        bare_delta = next((row for row in deltas if row["label"] == "bare_ground"), None)
        if bare_delta is not None and bare_delta["direction"] == "increase":
            lines.append("- Finding: bare-ground or burn-scar proxy area is predicted to increase.")
        else:
            lines.append("- Finding: no strong burn-scar expansion proxy is present.")
    elif profile == "flood_pulse":
        water_delta = next((row for row in deltas if row["label"] == "water"), None)
        if water_delta is not None and water_delta["direction"] == "increase":
            lines.append("- Finding: water extent is predicted to increase, consistent with a flood-pulse proxy.")
        else:
            lines.append("- Finding: no strong water-expansion signal is present.")
    elif profile == "oceanscout_ship_detection":
        analytics = tim_context["profile_analytics"]
        candidates = analytics.get("vessel_candidates") if isinstance(analytics, dict) else None
        count = len(candidates) if isinstance(candidates, list) else 0
        lines.append(
            f"- Finding: TiM-like maritime analytics produce {count} candidate presence indicator(s); "
            "these require corroboration and are not legal assertions."
        )
    else:
        lines.append("- Finding: this is a general brief; interpret TiM deltas as auxiliary model evidence.")
    lines.extend(
        [
            "- Confidence: moderate for procedural training supervision; validate with temporal imagery before action.",
            "- Limitations: procedural training supervision only; not live field truth.",
        ]
    )
    return "\n".join(lines)


def build_analysis_image_spec(
    *,
    profile: str,
    tile_stem: str,
    sentinel_fractions: dict[int, float],
    tim_fractions: dict[int, float],
    regions: list[RegionAnn],
) -> dict[str, Any]:
    """Serializable spec for a procedural TiM-style predicted analysis raster."""
    deltas = fraction_deltas(sentinel_fractions, tim_fractions)
    regions_px = [
        {
            "x1": int(r.bbox_xyxy[0]),
            "y1": int(r.bbox_xyxy[1]),
            "x2": int(r.bbox_xyxy[2]),
            "y2": int(r.bbox_xyxy[3]),
            "label": r.label,
            "class_id": r.class_id,
        }
        for r in regions
    ]
    return {
        "kind": "tim_predicted_analysis_raster",
        "profile": profile,
        "tile_stem": tile_stem,
        "size": 224,
        "sentinel_class_fractions": _named_fraction_map(sentinel_fractions),
        "tim_class_fractions": _named_fraction_map(tim_fractions),
        "deltas": deltas,
        "regions_px": regions_px,
        "palette": {k: list(v) for k, v in LAND_COVER_RGB.items()},
        "description": (
            "Procedural per-pixel class field sampled from TiM-like class fractions, with optional "
            "metadata region overlays when sidecar regions exist."
        ),
    }


def _hash_u01(*parts: str | int) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") / float(2**32)


def _pick_tim_label(u: float, tim_named: dict[str, float]) -> str:
    labels = [DYNAMIC_WORLD_CLASSES[i] for i in sorted(DYNAMIC_WORLD_CLASSES)]
    weights = [max(0.0, float(tim_named.get(lab, 0.0))) for lab in labels]
    total = sum(weights) or 1.0
    t = 0.0
    for lab, w in zip(labels, weights, strict=True):
        t += w / total
        if u < t:
            return lab
    return labels[-1]


def _accent_label_from_deltas(deltas: list[dict[str, Any]], *, min_delta: float = 0.02) -> str | None:
    pos = [d for d in deltas if float(d.get("delta", 0.0)) >= min_delta]
    if not pos:
        return None
    best = max(pos, key=lambda d: float(d["delta"]))
    return str(best.get("label"))


def _shade_rgb(rgb: tuple[int, int, int], *, x: int, y: int) -> tuple[int, int, int]:
    shade = 12 if ((x // 8) + (y // 8)) % 2 == 0 else 0
    return (min(255, rgb[0] + shade), min(255, rgb[1] + shade), min(255, rgb[2] + shade))


def render_analysis_image(spec: dict[str, Any], dest: Path) -> None:
    size = int(spec.get("size") or 224)
    profile = str(spec.get("profile") or "brief_only")
    tile_stem = str(spec.get("tile_stem") or "tile")
    tim_named = spec.get("tim_class_fractions")
    if not isinstance(tim_named, dict):
        tim_named = {}
    deltas = spec.get("deltas")
    if not isinstance(deltas, list):
        deltas = []
    regions_px = spec.get("regions_px")
    if not isinstance(regions_px, list):
        regions_px = []

    accent = _accent_label_from_deltas(deltas)

    data: list[tuple[int, int, int]] = []
    for y in range(size):
        for x in range(size):
            u = _hash_u01(tile_stem, profile, x, y)
            lab = _pick_tim_label(u, {k: float(v) for k, v in tim_named.items() if isinstance(k, str)})
            base = LAND_COVER_RGB.get(lab, (140, 140, 140))
            data.append(_shade_rgb(base, x=x, y=y))

    def _set_px(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            data[y * size + x] = _shade_rgb(rgb, x=x, y=y)

    if accent and regions_px:
        rgb_accent = LAND_COVER_RGB.get(accent, (200, 200, 200))
        for reg in regions_px:
            if not isinstance(reg, dict):
                continue
            try:
                x1, y1, x2, y2 = (
                    int(reg["x1"]),
                    int(reg["y1"]),
                    int(reg["x2"]),
                    int(reg["y2"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            x1c = max(0, min(size - 1, min(x1, x2)))
            x2c = max(0, min(size - 1, max(x1, x2)))
            y1c = max(0, min(size - 1, min(y1, y2)))
            y2c = max(0, min(size - 1, max(y1, y2)))
            reg_lab = str(reg.get("label") or "")
            if reg_lab and reg_lab != accent:
                for yy in range(y1c, y2c + 1):
                    for xx in range(x1c, x2c + 1):
                        u2 = _hash_u01(tile_stem, profile, "ov", xx, yy)
                        if u2 < 0.85:
                            _set_px(xx, yy, rgb_accent)

    img = Image.new("RGB", (size, size))
    img.putdata(data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")


def iter_row_image_paths(row: dict[str, Any]) -> Iterator[str]:
    for message in row.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image" and isinstance(part.get("image"), str):
                yield part["image"]


def validate_normalized_grounding_json(text: str) -> tuple[bool, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"json_decode:{e}"
    if not isinstance(data, list):
        return False, "not_a_list"
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return False, f"item_{i}_not_object"
        if str(item.get("label") or "").strip() == "":
            return False, f"item_{i}_empty_label"
        bb = item.get("bbox")
        if not isinstance(bb, list) or len(bb) != 4:
            return False, f"item_{i}_bad_bbox"
        x1, y1, x2, y2 = (float(x) for x in bb)
        eps = 1e-6
        if not (
            -eps <= x1 <= 1.0 + eps
            and -eps <= y1 <= 1.0 + eps
            and -eps <= x2 <= 1.0 + eps
            and -eps <= y2 <= 1.0 + eps
            and x1 < x2 - eps
            and y1 < y2 - eps
        ):
            return False, f"item_{i}_bbox_range"
    return True, "ok"


def row_prompt_blob(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for m in row.get("messages") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                    parts.append(p["text"])
    return "\n".join(parts)


def passes_bloat_filters(blob: str) -> tuple[bool, str]:
    low = blob.lower()
    for banned in BANNED_TRAINING_SUBSTRINGS:
        if banned.lower() in low:
            return False, f"bloat:{banned}"
    return True, "ok"


@dataclass
class SatBBoxMetadataSftConfig:
    dataset_root: Path
    split_filter: str = "all"  # all | train | validation | test
    max_rows: int = 0  # 0 = unlimited
    task_mix: frozenset[str] = field(default_factory=lambda: frozenset({"all"}))
    analysis_profiles: tuple[str, ...] = PRODUCTION_ANALYSIS_PROFILES
    include_mapbox_context: bool = True
    require_local_images: bool = True
    max_prompt_chars: int = 16_000
    absence_fraction_threshold: float = 0.03
    per_class_max: int = 6


@dataclass
class BuildStats:
    emitted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    by_task: Counter[str] = field(default_factory=Counter)
    prompt_chars_sum: int = 0
    bbox_counts: Counter[int] = field(default_factory=Counter)
    mapbox_paired: int = 0

    def record_prompt_len(self, row: dict[str, Any]) -> None:
        self.prompt_chars_sum += len(row_prompt_blob(row))

    def summary(self) -> dict[str, Any]:
        avg_prompt = (self.prompt_chars_sum / self.emitted) if self.emitted else 0.0
        return {
            "rows_emitted": self.emitted,
            "rows_dropped_by_reason": dict(self.dropped),
            "rows_by_task": dict(self.by_task),
            "avg_prompt_chars": round(avg_prompt, 2),
            "bbox_count_histogram": dict(sorted(self.bbox_counts.items())),
            "mapbox_paired_rows": self.mapbox_paired,
        }


def _want_tasks(cfg: SatBBoxMetadataSftConfig) -> set[str]:
    if "all" in cfg.task_mix:
        return {
            "production_analysis",
            "caption",
            "grounding",
            "per_class_grounding",
            "per_class_focus",
            "absence",
            "cross_view",
        }
    out: set[str] = set(cfg.task_mix)
    # ``per_class`` enables both grounding-per-label and class-focus captions.
    if "per_class" in out:
        out.discard("per_class")
        out.add("per_class_grounding")
        out.add("per_class_focus")
    if "analysis" in out:
        out.discard("analysis")
        out.add("production_analysis")
    return out


def _resolve_mapbox_rel(
    satellite_stem: str,
    mb_by_stem: dict[str, str],
) -> str | None:
    primary = mapbox_lookup_stem(satellite_stem)
    if primary in mb_by_stem:
        return mb_by_stem[primary]
    base = base_poi_id_from_stem(satellite_stem)
    if base in mb_by_stem:
        return mb_by_stem[base]
    return None


def _absence_class(
    regions: list[RegionAnn],
    fr: dict[int, float],
    *,
    threshold: float,
) -> tuple[int, str] | None:
    present_labels = {r.label for r in regions}
    present_ids = set(fr.keys()) | {r.class_id for r in regions}
    candidates: list[tuple[int, str]] = []
    for cid, name in DYNAMIC_WORLD_CLASSES.items():
        frac = fr.get(cid, 0.0)
        if frac > threshold:
            continue
        if cid in present_ids and name in present_labels:
            continue
        if any(r.class_id == cid for r in regions):
            continue
        candidates.append((cid, name))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    cid, name = candidates[0]
    return cid, name


def build_rows_for_sidecar(
    meta: dict[str, Any],
    *,
    tile_stem: str,
    sat_rel: str,
    mb_rel: str | None,
    cfg: SatBBoxMetadataSftConfig,
    leaked_bases: set[str],
    stats: BuildStats,
) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Yield ``(output_split, row, sidecar)``."""
    want = _want_tasks(cfg)
    base = base_poi_id_from_stem(tile_stem)
    if base in leaked_bases:
        stats.dropped["split_leakage"] += 1
        return

    out_split = _sidecar_split(meta, tile_stem=tile_stem)
    if cfg.split_filter != "all" and out_split != cfg.split_filter:
        return

    root = cfg.dataset_root
    if cfg.require_local_images and not (root / sat_rel).is_file():
        stats.dropped["missing_satellite_image"] += 1
        return
    analysis_image_paths = [sat_rel]
    if cfg.include_mapbox_context and mb_rel is not None:
        if not cfg.require_local_images or (root / mb_rel).is_file():
            analysis_image_paths.append(mb_rel)
        else:
            stats.dropped["missing_mapbox_still_analysis_context"] += 1

    ow = int(meta.get("output_size") or 224)
    oh = ow
    regions = regions_from_sidecar(meta.get("regions"), image_w=ow, image_h=oh)
    fr = parse_class_fractions(meta.get("class_fractions"))
    caption = str(meta.get("caption") or "").strip()

    def gate(row: dict[str, Any], *, task: str) -> bool:
        blob = row_prompt_blob(row)
        if len(blob) > cfg.max_prompt_chars:
            stats.dropped["prompt_too_long"] += 1
            return False
        ok, reason = passes_bloat_filters(blob)
        if not ok:
            stats.dropped[reason] += 1
            return False
        if task in ("grounding", "per_class_grounding"):
            msgs = row.get("messages")
            if isinstance(msgs, list) and len(msgs) >= 2:
                last = msgs[-1]
                if isinstance(last, dict):
                    cc = last.get("content")
                    if isinstance(cc, list) and cc:
                        t0 = cc[0].get("text") if isinstance(cc[0], dict) else None
                        if isinstance(t0, str):
                            vok, _ = validate_normalized_grounding_json(t0.strip())
                            if not vok:
                                stats.dropped["invalid_grounding_json"] += 1
                                return False
        stats.by_task[task] += 1
        stats.record_prompt_len(row)
        return True

    sample_prefix = tile_stem

    if "production_analysis" in want:
        if not fr:
            stats.dropped["no_class_fractions_analysis"] += 1
        else:
            sentinel_observation = {
                "source": "sentinel_2_sidecar",
                "tile_stem": tile_stem,
                "caption": caption,
                "class_fractions": _named_fraction_map(fr),
                "dominant_classes": dominant_classes(fr),
                "regions": [
                    {
                        "label": r.label,
                        "class_id": r.class_id,
                        "bbox_px": list(r.bbox_xyxy),
                        "area_px": r.area_px,
                    }
                    for r in regions
                ],
            }
            for raw_profile in cfg.analysis_profiles:
                profile = normalize_production_analysis_profile(raw_profile)
                if profile not in PRODUCTION_ANALYSIS_PROFILES:
                    stats.dropped[f"unknown_analysis_profile:{raw_profile}"] += 1
                    continue
                tim_fr = procedural_tim_fractions(fr, profile=profile)
                tim_context = build_procedural_tim_context(
                    meta=meta,
                    sentinel_fractions=fr,
                    profile=profile,
                    tim_fractions=tim_fr,
                )
                analysis_image_rel = (
                    f"analysis_images/{safe_sidecar_filename(sample_prefix)}__analysis_{profile}.png"
                )
                analysis_image_spec = build_analysis_image_spec(
                    profile=profile,
                    tile_stem=tile_stem,
                    sentinel_fractions=fr,
                    tim_fractions=tim_fr,
                    regions=regions,
                )
                row_image_paths = [*analysis_image_paths, analysis_image_rel]
                tim_json_for_prompt = tim_context_for_user_prompt(tim_context)
                user_txt = "\n".join(
                    [
                        "Production-like analysis input:",
                        f"- analysis_profile: {profile}",
                        "- Image sequence:",
                        "  1. Sentinel-2 chip (`images/...`) for visual interpretation (no separate text dump of chip metadata).",
                        *(
                            [
                                "  2. Mapbox still (`mapbox_stills/...`) from the input dataset, "
                                "included as auxiliary overhead context."
                            ]
                            if len(analysis_image_paths) > 1
                            else []
                        ),
                        f"  {len(analysis_image_paths) + 1}. TiM-style analysis image (`analysis_images/...`): "
                        "procedural predicted-class raster from TiM-like fractions, with optional "
                        "geometry-guided overlays.",
                        "- TiM-style analytics JSON (model-shaped; STAC / raw sidecar fields omitted):",
                        json.dumps(tim_json_for_prompt, ensure_ascii=False, indent=2),
                        "",
                        "Task: write the application-specific analytical summary. Ground dominant land-cover "
                        "claims in the Sentinel-2 imagery, then relate them to the TiM-shaped JSON above; "
                        "call out increases, decreases, confidence, and limitations.",
                    ]
                )
                assistant = build_analytical_summary(
                    profile=profile,
                    sentinel_fractions=fr,
                    tim_context=tim_context,
                )
                row = make_multi_image_vlm_message(
                    row_image_paths,
                    user_txt,
                    assistant,
                    system_text=PRODUCTION_ANALYSIS_SYSTEM,
                    metadata={
                        "sample_id": f"{sample_prefix}__analysis_{profile}",
                        "task": "production_analysis",
                        "analysis_profile": profile,
                        "tile_stem": tile_stem,
                        "split": out_split,
                        "image_paths": list(row_image_paths),
                        "analysis_image_path": analysis_image_rel,
                    },
                )
                if gate(row, task="production_analysis"):
                    if len(analysis_image_paths) > 1:
                        stats.mapbox_paired += 1
                    yield out_split, row, {
                        "sample_id": f"{sample_prefix}__analysis_{profile}",
                        "task": "production_analysis",
                        "analysis_profile": profile,
                        "tile_stem": tile_stem,
                        "split": out_split,
                        "image_paths": list(row_image_paths),
                        "analysis_image_path": analysis_image_rel,
                        "analysis_image_spec": analysis_image_spec,
                        "sentinel_sidecar": sentinel_observation,
                    }

    if "caption" in want:
        if not caption:
            stats.dropped["no_caption"] += 1
        else:
            row = caption_row(sat_rel, caption)
            if gate(row, task="caption"):
                yield out_split, row, {
                    "sample_id": f"{sample_prefix}__caption",
                    "task": "caption",
                    "tile_stem": tile_stem,
                    "split": out_split,
                    "image_paths": [sat_rel],
                }

    if "grounding" in want:
        if not regions:
            stats.dropped["no_regions_grounding"] += 1
        else:
            gj = regions_to_normalized_json(regions, image_w=ow, image_h=oh)
            row = grounding_row(sat_rel, "land-cover regions", gj)
            if gate(row, task="grounding"):
                stats.bbox_counts[len(regions)] += 1
                yield out_split, row, {
                    "sample_id": f"{sample_prefix}__ground_all",
                    "task": "grounding_all",
                    "tile_stem": tile_stem,
                    "split": out_split,
                    "image_paths": [sat_rel],
                }

    if ("per_class_grounding" in want or "per_class_focus" in want) and regions:
        by_label: dict[str, list[RegionAnn]] = {}
        for r in regions:
            by_label.setdefault(r.label, []).append(r)
        ordered = sorted(by_label.items(), key=lambda kv: sum(x.area_px for x in kv[1]), reverse=True)[
            : cfg.per_class_max
        ]
        for lab, sub in ordered:
            gj = regions_to_normalized_json(sub, image_w=ow, image_h=oh)
            if "per_class_grounding" in want:
                gr = grounding_row(sat_rel, f"**{lab}** land-cover regions", gj)
                if gate(gr, task="per_class_grounding"):
                    yield out_split, gr, {
                        "sample_id": f"{sample_prefix}__ground_{lab}",
                        "task": "grounding_per_class",
                        "tile_stem": tile_stem,
                        "split": out_split,
                        "image_paths": [sat_rel],
                        "class": lab,
                    }
            if "per_class_focus" in want:
                share = fr.get(sub[0].class_id, 0.0)
                ans = (
                    f"**{lab}** covers about {round(100.0 * share, 2)}% of valid pixels in the label raster "
                    "at this resolution; spatially it appears as one or more contiguous patches."
                )
                row = class_focus_caption_row(sat_rel, lab, ans)
                if gate(row, task="per_class_focus"):
                    yield out_split, row, {
                        "sample_id": f"{sample_prefix}__focus_{lab}",
                        "task": "class_focus",
                        "tile_stem": tile_stem,
                        "split": out_split,
                        "image_paths": [sat_rel],
                        "class": lab,
                    }

    if "absence" in want:
        ab = _absence_class(regions, fr, threshold=cfg.absence_fraction_threshold)
        if ab is None:
            stats.dropped["no_absence_candidate"] += 1
        else:
            _cid, name = ab
            user_q = (
                f"Given the aligned land-cover semantics for this tile, is **{name}** a substantive "
                "share of the scene? Answer briefly and conservatively."
            )
            assistant = (
                f"No clear evidence of a substantive **{name}** share in this tile at the labeled resolution; "
                "treat absence as uncertain if clouds, shadows, or mixed pixels dominate."
            )
            row = make_multi_image_vlm_message([sat_rel], user_q, assistant)
            if gate(row, task="absence"):
                yield out_split, row, {
                    "sample_id": f"{sample_prefix}__absence_{name}",
                    "task": "absence",
                    "tile_stem": tile_stem,
                    "split": out_split,
                    "image_paths": [sat_rel],
                    "absent_class": name,
                }

    if "cross_view" in want and cfg.include_mapbox_context and mb_rel is not None:
        if cfg.require_local_images and not (root / mb_rel).is_file():
            stats.dropped["missing_mapbox_still"] += 1
        else:
            user_txt = (
                f"{MAPBOX_OVERVIEW_PROMPT}\n\n"
                f"Dataset land-cover summary for the paired satellite chip: {caption or '(no caption)'}"
            )
            assistant = (
                "Overhead context shows coarse layout; the paired satellite chip and dataset labels indicate "
                f"dominant cover consistent with: {caption or 'the sidecar summary'}."
            )
            row = make_multi_image_vlm_message([mb_rel, sat_rel], user_txt, assistant)
            if gate(row, task="cross_view"):
                stats.mapbox_paired += 1
                yield out_split, row, {
                    "sample_id": f"{sample_prefix}__cross_view",
                    "task": "cross_view",
                    "tile_stem": tile_stem,
                    "split": out_split,
                    "image_paths": [mb_rel, sat_rel],
                }


def run_metadata_sft_build(cfg: SatBBoxMetadataSftConfig) -> tuple[list[tuple[str, dict[str, Any], dict[str, Any]]], BuildStats]:
    root = cfg.dataset_root.resolve()
    # Always index every split JSONL so stems resolve even when ``--split`` filters output rows.
    jsonl_files = iter_dataset_jsonl_files(root, split="all")
    sat_by_stem, mb_by_stem = index_jsonl_image_paths(jsonl_files)
    meta_paths = discover_metadata_paths(root)
    leaked = collect_split_leakage_bases(meta_paths)
    stats = BuildStats()
    out_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    for mp in meta_paths:
        if cfg.max_rows and stats.emitted >= cfg.max_rows:
            break
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats.dropped["bad_metadata_json"] += 1
            continue
        if not isinstance(meta, dict):
            stats.dropped["bad_metadata_shape"] += 1
            continue
        tile_stem = str(meta.get("tile_stem") or mp.stem).strip()
        sat_rel = sat_by_stem.get(tile_stem)
        if not sat_rel:
            stats.dropped["stem_not_in_jsonl"] += 1
            continue
        mb_rel = _resolve_mapbox_rel(tile_stem, mb_by_stem)
        row_iter = build_rows_for_sidecar(
            meta,
            tile_stem=tile_stem,
            sat_rel=sat_rel,
            mb_rel=mb_rel,
            cfg=cfg,
            leaked_bases=leaked,
            stats=stats,
        )
        while True:
            if cfg.max_rows and stats.emitted >= cfg.max_rows:
                break
            try:
                sp, row, side = next(row_iter)
            except StopIteration:
                break
            out_rows.append((sp, row, side))
            stats.emitted += 1
        if cfg.max_rows and stats.emitted >= cfg.max_rows:
            break
    return out_rows, stats


def safe_sidecar_filename(sample_id: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", sample_id.strip())[:200]
    return s or "row"


def write_split_jsonl_and_sidecars(
    rows: list[tuple[str, dict[str, Any], dict[str, Any]]],
    out_dir: Path,
    *,
    source_root: Path | None = None,
    copy_source_images: bool = True,
) -> None:
    out_dir = Path(out_dir)
    data_dir = out_dir / "data"
    meta_out = out_dir / "metadata" / "sft_metadata_rows"
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_out.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    copied: set[str] = set()
    for sp, row, side in rows:
        buckets.setdefault(sp, []).append(json.dumps(row, ensure_ascii=False))
        analysis_rel = side.get("analysis_image_path")
        analysis_spec = side.get("analysis_image_spec")
        if isinstance(analysis_rel, str) and isinstance(analysis_spec, dict):
            render_analysis_image(analysis_spec, out_dir / analysis_rel)
        if copy_source_images and source_root is not None:
            for rel in iter_row_image_paths(row):
                if rel.startswith("analysis_images/") or rel in copied:
                    continue
                src = Path(source_root) / rel
                dest = out_dir / rel
                if src.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    copied.add(rel)
        sid = safe_sidecar_filename(str(side.get("sample_id") or "row"))
        (meta_out / f"{sid}.json").write_text(
            json.dumps(side, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for split, lines in buckets.items():
        if not lines:
            continue
        p = data_dir / f"{split}.jsonl"
        p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
