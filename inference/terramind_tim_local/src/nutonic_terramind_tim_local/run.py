"""Build TerraMind TiM, run forward, return capped export dict."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from terratorch import BACKBONE_REGISTRY

from nutonic_terramind_tim_local.capture import attach_tim_sampler_capture
from nutonic_terramind_tim_local.terramind_patches import (
    apply_terramind_tim_runtime_hotfixes,
    terramind_patch_diagnostics,
)
from nutonic_terramind_tim_local.inputs_build import _build_inputs, load_run_config
from nutonic_terramind_tim_local.serialize import (
    build_profile_analytics,
    build_tim_modality_outputs,
    decode_coordinates_from_tim_dict,
    encoder_trace_summary,
    mean_arithmetic_latlon,
)

apply_terramind_tim_runtime_hotfixes()


def _hydration_included_location_ids_from_environ() -> frozenset[str] | None:
    """
    When set by ``run_hf_hydration_full.py`` after sv-lfm, restricts TiM ``cfg.batch`` rows.

    Format: comma-separated ``location_id`` values (same as ``hydration_included_location_ids.json``).
    For full parity, the TiM Job should merge ``runs/<cv>/reports/tim_batch_seed.json`` into the YAML
    so ``cfg.batch`` contains every included id before this filter runs.
    """
    raw = (os.environ.get("NUTONIC_HYDRATION_INCLUDED_LOCATION_IDS") or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    return frozenset(parts)


def _location_ensemble_cfg(cfg: Mapping[str, Any]) -> tuple[int, int, float, bool]:
    """``(n_samples, seed_base, input_noise_std, include_sample_coordinates)``."""
    block = cfg.get("location_ensemble")
    if not isinstance(block, dict):
        return 1, 42, 0.0, False
    n = int(block.get("n_samples", 1))
    seed_base = int(block.get("seed_base", 42))
    noise = float(block.get("input_noise_std", 0.0))
    inc = bool(block.get("include_sample_coordinates", False))
    return max(1, n), seed_base, noise, inc


def _set_ensemble_iteration_seed(seed: int) -> None:
    """
    Reseed global RNGs before each ensemble forward (identical inputs; sampler may use RNG).

    Uses ``seed_base + sample_index`` so each of the N passes is reproducible and distinct
    when TerraTorch / TiM draws stochasticity from torch, CUDA, ``random``, or NumPy.
    """
    s = int(seed) & 0xFFFFFFFFFFFFFFFF
    random.seed(s)
    np.random.seed(s % (2**32 - 1))
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


def _pair_from_wgs(wgs: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    if not wgs or not isinstance(wgs, dict):
        return None, None
    if wgs.get("nan"):
        return None, None
    lat, lon = wgs.get("latitude"), wgs.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        la, lo = float(lat), float(lon)
        if la == la and lo == lo:
            return la, lo
    return None, None


def _run_location_ensemble_forwards(
    model: torch.nn.Module,
    device: torch.device,
    base_inputs: dict[str, torch.Tensor],
    storage: dict[str, Any],
    *,
    n_samples: int,
    seed_base: int,
    input_noise_std: float,
) -> tuple[list[tuple[float | None, float | None]], list[Any], dict[str, Any]]:
    """Run ``n_samples`` forwards; return per-sample decoded pairs and last forward artifacts."""
    pairs: list[tuple[float | None, float | None]] = []
    last_enc: list[Any] = []
    last_tim: dict[str, Any] = {}
    for i in range(n_samples):
        _set_ensemble_iteration_seed(seed_base + i)
        inputs: dict[str, torch.Tensor]
        if input_noise_std > 0.0:
            inputs = {k: v + torch.randn_like(v) * input_noise_std for k, v in base_inputs.items()}
        else:
            inputs = {k: v.clone() for k, v in base_inputs.items()}
        with torch.no_grad():
            last_enc = model(inputs)
        last_tim = dict(storage.get("tim") or {})
        wgs = decode_coordinates_from_tim_dict(model, last_tim)
        pairs.append(_pair_from_wgs(wgs))
    return pairs, last_enc, last_tim


def _apply_location_mean_to_row(
    row: dict[str, Any],
    *,
    mean_lat: float,
    mean_lon: float,
    ensemble_summary: Mapping[str, Any],
    sample_coords: list[dict[str, float | None]] | None,
) -> None:
    tmo = row.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return
    coord: dict[str, Any] = {
        "kind": "coordinates_wgs84",
        "latitude": float(mean_lat),
        "longitude": float(mean_lon),
        "aggregate": "arithmetic_mean",
        "ensemble": dict(ensemble_summary),
    }
    tmo["Coordinates"] = coord
    row["ai_lat"] = float(mean_lat)
    row["ai_lon"] = float(mean_lon)
    row["location_ensemble"] = {
        **dict(ensemble_summary),
        "mean_latitude": float(mean_lat),
        "mean_longitude": float(mean_lon),
    }
    if sample_coords is not None:
        row["location_ensemble"]["samples"] = sample_coords


def _export_row(
    model: torch.nn.Module,
    enc_layers: list[Any],
    tim_raw: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    map_id: str,
    location_id: str,
    analysis_profile: str | None = None,
    inputs_aux: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ser = (cfg.get("serialization") or {})
    sample_limit = int(ser.get("tensor_sample_limit", 0))
    enc_sample = int(ser.get("encoder_tensor_sample_limit", 0))
    tim_policy = str(ser.get("tim_outputs", "product"))
    export_cfg = cfg.get("export") or {}

    tim_modality_outputs = build_tim_modality_outputs(
        model, tim_raw, tensor_sample_limit=sample_limit, policy=tim_policy
    )
    profile = str(
        analysis_profile
        or export_cfg.get("analysis_profile")
        or cfg.get("analysis_profile")
        or "brief_only"
    )

    trace = []
    if ser.get("include_encoder_trace", True) and isinstance(enc_layers, list):
        mode = str(ser.get("encoder_trace_mode", "last")).lower()
        layers_sel = enc_layers if mode == "all" else [enc_layers[-1]]
        trace = encoder_trace_summary(layers_sel, sample_limit=enc_sample)

    row: dict[str, Any] = {
        "content_version": str(cfg.get("content_version", "nutonic.tim_local.v1")),
        "engine": {
            "terratorch": True,
            "model_id": str(cfg["model_id"]),
            "input_modalities": list(cfg["modalities"]),
            "output_modalities_tim": list(cfg["tim_modalities"]),
            "modalities": list(cfg["modalities"]),
            "tim_modalities": list(cfg["tim_modalities"]),
            "merge_method": cfg.get("merge_method", "mean"),
            "tim_outputs": tim_policy,
            "patch_diagnostics": terramind_patch_diagnostics(),
        },
        "map_id": map_id,
        "location_id": location_id,
        "analysis_profile": profile,
        "tim_modality_outputs": tim_modality_outputs,
        "profile_analytics": build_profile_analytics(profile, tim_modality_outputs, inputs_aux),
        "encoder_trace": trace,
    }
    if ser.get("include_tim_raw_keys", False):
        row["engine"]["tim_raw_keys"] = sorted(tim_raw.keys())
    if inputs_aux:
        row["inputs_meta"] = dict(inputs_aux)

    coords = tim_modality_outputs.get("Coordinates")
    if export_cfg.get("include_ai_guess_row", True) and isinstance(coords, dict):
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            row["ai_lat"] = float(lat)
            row["ai_lon"] = float(lon)

    return row


def _export_for_inputs(
    model: torch.nn.Module,
    device: torch.device,
    cfg: Mapping[str, Any],
    storage: dict[str, Any],
    *,
    inputs: dict[str, torch.Tensor],
    inputs_aux: Mapping[str, Any] | None,
    map_id: str,
    location_id: str,
    analysis_profile: str | None = None,
) -> dict[str, Any]:
    """
    One catalog row worth of tensors → export row, optionally with ``location_ensemble`` mean.

    When ``location_ensemble.n_samples`` > 1, runs multiple forwards with **per-sample
    global seeding** (``seed_base + i``) and **identical cloned inputs** (optional
    ``input_noise_std`` only when set > 0). ``Coordinates`` / ``ai_lat`` / ``ai_lon`` are
    the arithmetic mean of finite WGS84 decodes; other modalities come from the last forward.
    """
    n_samp, seed0, noise_std, inc_samples = _location_ensemble_cfg(cfg)
    if n_samp > 1:
        pairs, enc_layers, tim_raw = _run_location_ensemble_forwards(
            model,
            device,
            inputs,
            storage,
            n_samples=n_samp,
            seed_base=seed0,
            input_noise_std=noise_std,
        )
        mean_lat, mean_lon = mean_arithmetic_latlon(pairs)
        out_row = _export_row(
            model,
            enc_layers,
            tim_raw,
            cfg,
            map_id=map_id,
            location_id=location_id,
            analysis_profile=analysis_profile,
            inputs_aux=inputs_aux,
        )
        n_fin = sum(1 for la, lo in pairs if la is not None and lo is not None)
        summary: dict[str, Any] = {
            "n_samples": n_samp,
            "n_finite": n_fin,
            "seed_base": seed0,
            "input_noise_std": noise_std,
            "model_id": str(cfg.get("model_id", "")),
        }
        sample_list: list[dict[str, float | None]] | None = None
        if inc_samples:
            sample_list = [
                {
                    "latitude": None if la is None else float(la),
                    "longitude": None if lo is None else float(lo),
                }
                for la, lo in pairs
            ]
        if mean_lat is not None and mean_lon is not None:
            _apply_location_mean_to_row(
                out_row,
                mean_lat=mean_lat,
                mean_lon=mean_lon,
                ensemble_summary=summary,
                sample_coords=sample_list,
            )
        else:
            out_row["location_ensemble"] = {**summary, "mean_latitude": None, "mean_longitude": None, "mean_failed": True}
            if sample_list is not None:
                out_row["location_ensemble"]["samples"] = sample_list
        return out_row

    with torch.no_grad():
        enc_layers = model(inputs)
    tim_raw = storage.get("tim") or {}
    return _export_row(
        model,
        enc_layers,
        tim_raw,
        cfg,
        map_id=map_id,
        location_id=location_id,
        analysis_profile=analysis_profile,
        inputs_aux=inputs_aux,
    )


def run_tim_forward_export(cfg: Mapping[str, Any]) -> dict[str, Any]:
    device = torch.device(str(cfg.get("device", "cpu")))
    model = BACKBONE_REGISTRY.build(
        str(cfg["model_id"]),
        pretrained=bool(cfg.get("pretrained", True)),
        modalities=list(cfg["modalities"]),
        tim_modalities=list(cfg["tim_modalities"]),
        merge_method=cfg.get("merge_method", "mean"),
    )
    model = model.to(device)
    model.eval()

    storage: dict[str, Any] = {}
    attach_tim_sampler_capture(model.sampler, storage)

    batch_rows = cfg.get("batch")
    export_cfg = cfg.get("export") or {}
    if isinstance(batch_rows, list) and batch_rows:
        raise ValueError("Use run_tim_batch_export for config.batch lists")

    inputs, inputs_aux = _build_inputs(cfg, device)
    return _export_for_inputs(
        model,
        device,
        cfg,
        storage,
        inputs=inputs,
        inputs_aux=inputs_aux,
        map_id=str(export_cfg.get("map_id", "unset_map")),
        location_id=str(export_cfg.get("location_id", "unset_location")),
        analysis_profile=str(export_cfg.get("analysis_profile") or cfg.get("analysis_profile") or "brief_only"),
    )


def run_tim_batch_export(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run one shared model over ``cfg.batch`` rows (each may set ``rgb_mode`` / ``rgb_jpeg``)."""
    device = torch.device(str(cfg.get("device", "cpu")))
    model = BACKBONE_REGISTRY.build(
        str(cfg["model_id"]),
        pretrained=bool(cfg.get("pretrained", True)),
        modalities=list(cfg["modalities"]),
        tim_modalities=list(cfg["tim_modalities"]),
        merge_method=cfg.get("merge_method", "mean"),
    )
    model = model.to(device)
    model.eval()

    storage: dict[str, Any] = {}
    attach_tim_sampler_capture(model.sampler, storage)

    batch_rows = cfg.get("batch")
    if not isinstance(batch_rows, list) or not batch_rows:
        raise ValueError("run_tim_batch_export requires config.batch as a non-empty list")

    only = _hydration_included_location_ids_from_environ()
    if only is not None:
        filtered = [r for r in batch_rows if isinstance(r, dict) and str(r.get("location_id", "")).strip() in only]
        if len(filtered) < len(only):
            print(
                "run_tim_batch_export: warning: fewer YAML batch rows than "
                f"NUTONIC_HYDRATION_INCLUDED_LOCATION_IDS ({len(filtered)} vs {len(only)}); "
                "ensure sv-lfm uploaded runs/<cv>/reports/tim_batch_seed.json and the TiM entrypoint merged it.",
                file=sys.stderr,
            )
        if not filtered:
            raise ValueError(
                "run_tim_batch_export: NUTONIC_HYDRATION_INCLUDED_LOCATION_IDS filtered out every batch row"
            )
        batch_rows = filtered

    out_rows: list[dict[str, Any]] = []
    for row in batch_rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("map_id", "")).strip()
        lid = str(row.get("location_id", "")).strip()
        if not mid or not lid:
            raise ValueError("Each batch row needs map_id and location_id")
        inputs, inputs_aux = _build_inputs(cfg, device, row=row)
        out_rows.append(
            _export_for_inputs(
                model,
                device,
                cfg,
                storage,
                inputs=inputs,
                inputs_aux=inputs_aux,
                map_id=mid,
                location_id=lid,
                analysis_profile=str(row.get("analysis_profile") or cfg.get("analysis_profile") or "brief_only"),
            )
        )
    return out_rows


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, obj: Mapping[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
