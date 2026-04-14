"""Build TerraMind TiM, run forward, return capped export dict."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml
from PIL import Image
from terratorch import BACKBONE_REGISTRY

from nutonic_terramind_tim_local.capture import attach_tim_sampler_capture
from nutonic_terramind_tim_local.serialize import build_tim_modality_outputs, encoder_trace_summary
from nutonic_terramind_tim_local.s2_stac import apply_reflectance_scale, load_s2l2a_patch_np, stac_s2_params_from_cfg


def load_run_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    return raw


def _resolve_rgb_jpeg_path(cfg: Mapping[str, Any], path: str | None) -> str | None:
    """Resolve ``rgb_jpeg`` against optional ``paths.repo_root`` (or cwd) for portable YAML."""
    if path is None or not isinstance(path, str) or not path.strip():
        return path
    raw = path.strip()
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())
    roots = (cfg.get("paths") or {}).get("repo_root")
    candidates: list[Path] = []
    if roots is not None:
        base = Path(str(roots)).expanduser()
        base = base.resolve() if base.is_absolute() else (Path.cwd() / base).resolve()
        candidates.append((base / raw).resolve())
    candidates.append((Path.cwd() / raw).resolve())
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return raw


def _rgb_tensor(
    *,
    device: torch.device,
    mode: str,
    batch_size: int,
    jpeg_path: str | None,
) -> torch.Tensor:
    mode_l = mode.lower()
    if mode_l == "zeros":
        return torch.zeros(batch_size, 3, 224, 224, device=device)
    if mode_l == "random":
        return torch.randn(batch_size, 3, 224, 224, device=device)
    if mode_l == "jpeg":
        if not jpeg_path:
            raise ValueError("inputs.mode=jpeg requires inputs.rgb_jpeg or batch[].rgb_jpeg")
        img = Image.open(jpeg_path).convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
        arr = torch.from_numpy(np.array(img)).float() / 255.0
        arr = arr.permute(2, 0, 1).unsqueeze(0).to(device)
        if batch_size != 1:
            raise ValueError("jpeg RGB mode currently supports batch_size=1")
        return arr
    raise ValueError(f"Unsupported RGB inputs.mode: {mode!r}")


def _is_rgb_modality(name: str) -> bool:
    return name.strip().upper() in ("RGB", "S2RGB")


def _is_s2l2a_modality(name: str) -> bool:
    return "S2L2A" in name.upper()


def _s2_tensor(
    *,
    device: torch.device,
    mode: str,
    batch_size: int,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[torch.Tensor, dict[str, Any] | None]:
    mode_l = mode.lower()
    if mode_l in ("zeros", "random"):
        t = torch.zeros(batch_size, 12, 224, 224, device=device) if mode_l == "zeros" else torch.randn(batch_size, 12, 224, 224, device=device)
        if mode_l == "random":
            t = t * 500.0 + 800.0
        return t, None
    if mode_l == "stac":
        if batch_size != 1:
            raise ValueError("S2L2A STAC mode currently supports batch_size=1")
        s2 = stac_s2_params_from_cfg(in_cfg, row)
        if s2.get("lat") is None or s2.get("lon") is None:
            raise ValueError("S2 STAC mode requires lat/lon in inputs.s2, inputs root, or batch row")
        lat = float(s2["lat"])
        lon = float(s2["lon"])
        dt = str(s2.get("datetime") or in_cfg.get("datetime") or "").strip()
        if not dt:
            raise ValueError("inputs.s2.datetime (or inputs.datetime / batch row) is required for S2 STAC mode")
        stack, meta = load_s2l2a_patch_np(
            lat=lat,
            lon=lon,
            datetime_range=dt,
            stac_url=str(s2.get("stac_url") or "https://earth-search.aws.element84.com/v1"),
            collection=str(s2.get("collection") or "sentinel-2-l2a"),
            half_km=float(s2.get("half_km", 12.0)),
            patch_hw=int(s2.get("patch_hw", 224)),
            max_cloud=float(s2.get("max_cloud", 60.0)),
            asset_keys=s2.get("asset_keys"),
            max_items=int(s2.get("max_items", 20)),
        )
        stack = apply_reflectance_scale(stack, s2)
        t = torch.from_numpy(stack).unsqueeze(0).to(device)
        return t, meta
    raise ValueError(f"Unsupported S2L2A inputs.mode: {mode!r}")


def _tensor_for_modality(
    mod: str,
    *,
    cfg: Mapping[str, Any],
    device: torch.device,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
    per_mod: Mapping[str, Any],
) -> tuple[torch.Tensor, dict[str, Any] | None]:
    mod_u = mod.strip()
    block = per_mod.get(mod_u) or per_mod.get(mod_u.upper()) or {}
    bs = int(row.get("batch_size") or block.get("batch_size") or in_cfg.get("batch_size", 1))
    if _is_rgb_modality(mod_u):
        mode = str(row.get("rgb_mode") or block.get("mode") or in_cfg.get("mode", "random")).lower()
        jpeg = row.get("rgb_jpeg") or block.get("rgb_jpeg") or in_cfg.get("rgb_jpeg")
        jpeg_r = _resolve_rgb_jpeg_path(cfg, jpeg if isinstance(jpeg, str) else None)
        return _rgb_tensor(device=device, mode=mode, batch_size=bs, jpeg_path=jpeg_r), None
    if _is_s2l2a_modality(mod_u):
        mode = str(
            row.get("s2_mode")
            or block.get("s2_mode")
            or block.get("mode")
            or in_cfg.get("s2_mode")
            or "random"
        ).lower()
        return _s2_tensor(device=device, mode=mode, batch_size=bs, in_cfg=in_cfg, row=row)
    raise NotImplementedError(f"Auto-inputs not implemented for modality {mod_u!r} (extend run.py).")


def _build_inputs(
    cfg: Mapping[str, Any], device: torch.device, row: Mapping[str, Any] | None = None
) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    in_cfg = cfg.get("inputs") or {}
    row = row or {}
    modalities = list(cfg.get("modalities") or [])
    if not modalities:
        raise ValueError("config.modalities must be non-empty")
    per_mod = in_cfg.get("by_modality") or {}
    if per_mod and not isinstance(per_mod, dict):
        raise ValueError("inputs.by_modality must be a mapping when set")
    out: dict[str, torch.Tensor] = {}
    aux: dict[str, Any] = {}
    for mod in modalities:
        if not isinstance(mod, str):
            raise ValueError("config.modalities entries must be strings for this runner")
        tensor, s2_meta = _tensor_for_modality(
            mod, cfg=cfg, device=device, in_cfg=in_cfg, row=row, per_mod=per_mod
        )
        out[mod] = tensor
        if s2_meta is not None:
            aux["s2_stac"] = s2_meta
            aux["s2_stac_modality_key"] = mod
    return out, aux


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
