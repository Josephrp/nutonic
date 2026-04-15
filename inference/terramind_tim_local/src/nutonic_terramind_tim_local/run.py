"""Build TerraMind TiM, run forward, return capped export dict."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import torch
from terratorch import BACKBONE_REGISTRY

from nutonic_terramind_tim_local.capture import attach_tim_sampler_capture
from nutonic_terramind_tim_local.terramind_patches import apply_terramind_coord_decode_hotfix
from nutonic_terramind_tim_local.inputs_build import _build_inputs, load_run_config
from nutonic_terramind_tim_local.serialize import build_tim_modality_outputs, encoder_trace_summary

apply_terramind_coord_decode_hotfix()


def _export_row(
    model: torch.nn.Module,
    enc_layers: list[Any],
    tim_raw: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    map_id: str,
    location_id: str,
    inputs_aux: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ser = (cfg.get("serialization") or {})
    sample_limit = int(ser.get("tensor_sample_limit", 0))
    enc_sample = int(ser.get("encoder_tensor_sample_limit", 0))
    tim_policy = str(ser.get("tim_outputs", "product"))

    tim_modality_outputs = build_tim_modality_outputs(
        model, tim_raw, tensor_sample_limit=sample_limit, policy=tim_policy
    )

    trace = []
    if ser.get("include_encoder_trace", True) and isinstance(enc_layers, list):
        mode = str(ser.get("encoder_trace_mode", "last")).lower()
        layers_sel = enc_layers if mode == "all" else [enc_layers[-1]]
        trace = encoder_trace_summary(layers_sel, sample_limit=enc_sample)

    export_cfg = cfg.get("export") or {}
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
        },
        "map_id": map_id,
        "location_id": location_id,
        "tim_modality_outputs": tim_modality_outputs,
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
    with torch.no_grad():
        enc_layers = model(inputs)

    tim_raw = storage.get("tim") or {}
    return _export_row(
        model,
        enc_layers,
        tim_raw,
        cfg,
        map_id=str(export_cfg.get("map_id", "unset_map")),
        location_id=str(export_cfg.get("location_id", "unset_location")),
        inputs_aux=inputs_aux,
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

    out_rows: list[dict[str, Any]] = []
    for row in batch_rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("map_id", "")).strip()
        lid = str(row.get("location_id", "")).strip()
        if not mid or not lid:
            raise ValueError("Each batch row needs map_id and location_id")
        inputs, inputs_aux = _build_inputs(cfg, device, row=row)
        with torch.no_grad():
            enc_layers = model(inputs)
        tim_raw = storage.get("tim") or {}
        out_rows.append(
            _export_row(
                model,
                enc_layers,
                tim_raw,
                cfg,
                map_id=mid,
                location_id=lid,
                inputs_aux=inputs_aux,
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
