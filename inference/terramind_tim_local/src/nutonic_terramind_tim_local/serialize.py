"""Schema-capped JSON serialization for TiM tensors + NU:TONIC-facing aliases."""

from __future__ import annotations

from typing import Any, Mapping

import torch


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


def encoder_trace_summary(
    layers: list[torch.Tensor],
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, t in enumerate(layers):
        out.append({"layer": i, **_tensor_stats(t, sample_limit)})
    return out
