"""Schema-capped JSON serialization for TiM tensors + NU:TONIC-facing aliases."""

from __future__ import annotations

from typing import Any, Mapping

import torch

from nutonic_terramind_tim_local.oceanscout_policy import OCEANSCOUT_SHORELINE_POLICY


def _tensor_stats(t: torch.Tensor, sample_limit: int) -> dict[str, Any]:
    t = t.detach().float().cpu()
    flat = t.reshape(-1)
    n = flat.numel()
    sample: list[float] | None = None
    if sample_limit > 0:
        if n <= sample_limit:
            sample = flat.tolist()
        else:
            step = max(1, n // sample_limit)
            sample = flat[::step][:sample_limit].tolist()
    out: dict[str, Any] = {
        "dtype": str(t.dtype),
        "shape": list(t.shape),
        "numel": int(n),
        "mean": float(flat.mean().item()) if n else 0.0,
        "std": float(flat.std(unbiased=False).item()) if n else 0.0,
        "min": float(flat.min().item()) if n else 0.0,
        "max": float(flat.max().item()) if n else 0.0,
    }
    if sample is not None:
        out["sample"] = sample
    return out


def serialize_tim_entry(
    key: str,
    value: Mapping[str, Any],
    *,
    sample_limit: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {"internal_key": key}
    if not isinstance(value, dict):
        out["repr"] = repr(value)[:2000]
        return out
    for sk, sv in value.items():
        if isinstance(sv, torch.Tensor):
            out[sk] = _tensor_stats(sv, sample_limit)
        else:
            out[sk] = repr(sv)[:2000]
    return out


def mean_arithmetic_latlon(
    pairs: list[tuple[float | None, float | None]],
) -> tuple[float | None, float | None]:
    """Arithmetic mean over finite (lat, lon) pairs; ignores missing or NaN samples."""
    finite = [
        (la, lo)
        for la, lo in pairs
        if la is not None
        and lo is not None
        and la == la
        and lo == lo  # NaN
    ]
    if not finite:
        return None, None
    n = len(finite)
    return sum(la for la, _ in finite) / n, sum(lo for _, lo in finite) / n


def decode_coordinates_from_tim_dict(model: Any, tim_dict: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return decoded WGS84 dict (same schema as ``Coordinates``) or ``None`` if missing."""
    blk = tim_dict.get("coords")
    if not isinstance(blk, dict):
        return None
    return _coords_wgs84_from_model(model, blk)


def _coords_wgs84_from_model(model: Any, coords_block: Mapping[str, Any]) -> dict[str, Any] | None:
    tok = getattr(model, "tokenizer", None)
    if tok is None or "coords" not in tok:
        return None
    try:
        decoded = tok["coords"].decode_text({"coords": dict(coords_block)})
    except Exception as exc:  # noqa: BLE001 — best-effort decode for batch tooling
        return {"kind": "coordinates_wgs84", "decode_error": str(exc)[:500]}
    if not decoded:
        return None
    lon, lat = decoded[0]
    if lon != lon or lat != lat:  # NaN
        return {"kind": "coordinates_wgs84", "latitude": None, "longitude": None, "nan": True}
    return {
        "kind": "coordinates_wgs84",
        "latitude": float(lat),
        "longitude": float(lon),
    }


def build_tim_modality_outputs(
    model: Any,
    tim_dict: Mapping[str, Any],
    *,
    tensor_sample_limit: int,
    policy: str = "product",
) -> dict[str, Any]:
    """
    Map internal TerraTorch keys (``tok_lulc@224``, ``coords``, …) to JSON-safe structures.

    ``policy``:
    - ``product`` — compact PRO-facing view: ``Coordinates`` (decoded WGS84), ``LULC``,
      token keys as ``tok_*``, and untokenized inputs grouped under ``_inputs``.
    - ``full`` — every TiM dict key is serialized at the top level (no silent drops),
      plus ``Coordinates`` when ``coords`` decode succeeds (same as product).
    """
    policy_l = policy.strip().lower()
    if policy_l not in ("product", "full"):
        raise ValueError(f"serialization.tim_outputs must be 'product' or 'full', got {policy!r}")

    outputs: dict[str, Any] = {}

    if policy_l == "full":
        for internal_key, block in tim_dict.items():
            if isinstance(block, dict):
                outputs[internal_key] = serialize_tim_entry(internal_key, block, sample_limit=tensor_sample_limit)
            else:
                outputs[internal_key] = {"internal_key": internal_key, "repr": repr(block)[:2000]}
        if "coords" in tim_dict and isinstance(tim_dict["coords"], dict):
            wgs = _coords_wgs84_from_model(model, tim_dict["coords"])
            if wgs is not None:
                outputs["Coordinates"] = wgs
        return outputs

    for internal_key, block in tim_dict.items():
        if internal_key.startswith("untok_"):
            outputs.setdefault("_inputs", {})[internal_key] = serialize_tim_entry(
                internal_key, block, sample_limit=tensor_sample_limit
            )
            continue

        if internal_key == "coords":
            wgs = _coords_wgs84_from_model(model, block)
            if wgs is not None:
                outputs["Coordinates"] = wgs
            outputs["_internal_coords"] = serialize_tim_entry(internal_key, block, sample_limit=tensor_sample_limit)
            continue

        if "lulc" in internal_key.lower():
            outputs.setdefault("LULC", serialize_tim_entry(internal_key, block, sample_limit=tensor_sample_limit))
            continue

        if internal_key.startswith("tok_"):
            outputs[internal_key] = serialize_tim_entry(internal_key, block, sample_limit=tensor_sample_limit)

    return outputs


def build_profile_analytics(
    analysis_profile: str | None,
    tim_modality_outputs: Mapping[str, Any],
    inputs_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = (analysis_profile or "brief_only").strip()
    if profile == "wildfire":
        return _wildfire_analytics(tim_modality_outputs, inputs_meta)
    if profile == "flood_pulse":
        return _flood_analytics(tim_modality_outputs, inputs_meta)
    if profile == "land_use_change":
        return _land_shift_analytics(tim_modality_outputs, inputs_meta)
    if profile == "oceanscout_ship_detection":
        return _oceanscout_analytics(tim_modality_outputs, inputs_meta)
    return {
        "profile": "brief_only",
        "schema_version": "1.0",
        "summary": {"kind": "brief_context", "confidence": "not_applicable"},
    }


def _base_profile_block(profile: str, inputs_meta: Mapping[str, Any] | None) -> dict[str, Any]:
    stac = {}
    if isinstance(inputs_meta, Mapping):
        raw = inputs_meta.get("s2_stac")
        if isinstance(raw, Mapping):
            stac = {
                "item_id": raw.get("stac_item_id"),
                "datetime": raw.get("stac_datetime"),
                "cloud_pct": raw.get("eo_cloud_cover"),
            }
    return {
        "profile": profile,
        "schema_version": "1.0",
        "scene_provenance": stac or None,
        "thresholds": {"schema_version": "1.0"},
    }


def _wildfire_analytics(
    tim_modality_outputs: Mapping[str, Any],
    inputs_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = _base_profile_block("wildfire", inputs_meta)
    out["burn_change"] = {
        "changed_area_pct": None,
        "hotspot_count": 0,
        "confidence_bins": {"low": 0, "medium": 0, "high": 0},
        "source_keys": sorted(tim_modality_outputs.keys()),
        "thresholds": {"burn_index_delta": None, "min_cluster_px": None},
    }
    return out


def _flood_analytics(
    tim_modality_outputs: Mapping[str, Any],
    inputs_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = _base_profile_block("flood_pulse", inputs_meta)
    out["water_change"] = {
        "expanded_area_pct": None,
        "inundation_polygon_count": 0,
        "confidence_bins": {"low": 0, "medium": 0, "high": 0},
        "source_keys": sorted(tim_modality_outputs.keys()),
        "thresholds": {"water_probability": None, "min_polygon_area_m2": None},
    }
    return out


def _land_shift_analytics(
    tim_modality_outputs: Mapping[str, Any],
    inputs_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = _base_profile_block("land_use_change", inputs_meta)
    out["land_transition"] = {
        "transition_matrix": [],
        "top_transitions": [],
        "raw_counts_total": 0,
        "normalized_total_pct": 0.0,
        "source_keys": sorted(tim_modality_outputs.keys()),
    }
    return out


def _oceanscout_analytics(
    tim_modality_outputs: Mapping[str, Any],
    inputs_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = _base_profile_block("oceanscout_ship_detection", inputs_meta)
    out["vessel_candidates"] = []
    out["observation_coverage"] = {
        "valid_observation_count": None,
        "cloud_masked_count": None,
        "glint_limited_count": None,
        "no_observation_count": None,
        "normalization": "valid_observation_count",
    }
    out["evidence_level"] = "tim_pseudosar_plus_lulc" if "LULC" in tim_modality_outputs else "optical_only"
    out["confidence"] = {"method": "profile_schema_v1", "bins": {"low": 0, "medium": 0, "high": 0}}
    out["notices"] = [
        "Candidate vessel detections are presence indicators and require corroboration.",
        "Pseudo-SAR-like TiM outputs are not equivalent to true SAR observations.",
    ]
    out["limitations"] = ["cloud", "sun_glint", "shoreline_ambiguity", "optical_only_constraints"]
    out["shoreline_policy"] = dict(OCEANSCOUT_SHORELINE_POLICY)
    return out


def encoder_trace_summary(
    layers: list[torch.Tensor],
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, t in enumerate(layers):
        out.append({"layer": i, **_tensor_stats(t, sample_limit)})
    return out
