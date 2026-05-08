"""Build per-modality input tensors for TerraMind TiM (no TerraTorch import)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml
from PIL import Image

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


def _rgb_from_s12_reflectance(s12: torch.Tensor) -> torch.Tensor:
    """
    TerraMind ``RGB`` / ``untok_sen2rgb@224`` expects **Sentinel-2** RED, GREEN, BLUE
    (same numeric range as S2L2A, ~reflectance×10⁴), not 8-bit aerial JPEGs.

    ``s12`` channel order matches ``s2_stac.EARTH_SEARCH_S2L2A_ASSET_KEYS`` / TerraTorch
    ``PRETRAINED_BANDS['untok_sen2l2a@224']``: … BLUE(1), GREEN(2), RED(3), …
    """
    if s12.ndim != 4 or s12.shape[1] < 12:
        raise ValueError(f"Expected S2L2A tensor (B,12,H,W), got {tuple(s12.shape)}")
    red_i, green_i, blue_i = 3, 2, 1
    return s12[:, [red_i, green_i, blue_i], :, :].contiguous()


def _is_rgb_modality(name: str) -> bool:
    return name.strip().upper() in ("RGB", "S2RGB")


def _is_s2l2a_modality(name: str) -> bool:
    return "S2L2A" in name.upper()


_PROFILE_INPUT_DEFAULTS: dict[str, dict[str, Any]] = {
    "wildfire": {"datetime_window_days": 45, "max_cloud": 30.0, "temporal_slices": ("t0", "t1")},
    "oceanscout_ship_detection": {
        "datetime_window_days": 21,
        "max_cloud": 35.0,
        "temporal_slices": ("t0", "t1", "t2"),
    },
    "land_use_change": {"datetime_window_days": 730, "max_cloud": 40.0, "temporal_slices": ("t0", "t1")},
    "flood_pulse": {"datetime_window_days": 30, "max_cloud": 50.0, "temporal_slices": ("t0", "t1")},
    "brief_only": {"datetime_window_days": 120, "max_cloud": 60.0, "temporal_slices": ("t1",)},
}


def profile_input_defaults(analysis_profile: str | None) -> dict[str, Any]:
    key = (analysis_profile or "brief_only").strip() or "brief_only"
    if key == "vessel_monitoring":
        key = "oceanscout_ship_detection"
    return dict(_PROFILE_INPUT_DEFAULTS.get(key, _PROFILE_INPUT_DEFAULTS["brief_only"]))


def _analysis_profile(in_cfg: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return str(row.get("analysis_profile") or in_cfg.get("analysis_profile") or "brief_only")


def _default_datetime_interval(days: int) -> str:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, int(days)))
    return f"{start.isoformat()}/{end.isoformat()}"


def _previous_datetime_interval(datetime_interval: str, days: int) -> str:
    raw_start, sep, raw_end = datetime_interval.partition("/")
    if not sep:
        return datetime_interval
    start = _parse_interval_date(raw_start)
    end = _parse_interval_date(raw_end)
    if start is None:
        return datetime_interval
    width = max(1, (end - start).days if end is not None else int(days))
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=width)
    return f"{prev_start.isoformat()}/{prev_end.isoformat()}"


def _parse_interval_date(value: str) -> Any | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _s2_params_with_profile_defaults(in_cfg: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    s2 = stac_s2_params_from_cfg(in_cfg, row)
    profile_defaults = profile_input_defaults(_analysis_profile(in_cfg, row))
    s2.setdefault("max_cloud", profile_defaults["max_cloud"])
    s2.setdefault("datetime", _default_datetime_interval(int(profile_defaults["datetime_window_days"])))
    return s2


def _stac_s12_tensor(
    device: torch.device,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[torch.Tensor, dict[str, Any]]:
    """One STAC read → ``(1,12,H,W)`` float tensor on ``device`` + STAC metadata."""
    s2 = _s2_params_with_profile_defaults(in_cfg, row)
    return _stac_s12_tensor_from_params(device, s2)


def _stac_s12_tensor_from_params(
    device: torch.device,
    s2: Mapping[str, Any],
    *,
    temporal_slice: str | None = None,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """One STAC read from resolved params → ``(1,12,H,W)`` tensor + metadata."""
    if s2.get("lat") is None or s2.get("lon") is None:
        raise ValueError("STAC S2 requires lat/lon in inputs.s2, inputs root, or batch row")
    lat = float(s2["lat"])
    lon = float(s2["lon"])
    dt = str(s2.get("datetime") or "").strip()
    if not dt:
        raise ValueError("inputs.s2.datetime (or inputs.datetime / batch row) is required for STAC S2")
    patch = load_s2l2a_patch_np(
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
        scene_id=str(s2["scene_id"]) if s2.get("scene_id") else None,
    )
    stack, meta = _patch_result_parts(patch)
    if temporal_slice:
        meta["temporal_slice"] = temporal_slice
    stack = apply_reflectance_scale(stack, s2)
    t = _torch_tensor_from_np(stack).unsqueeze(0).to(device)
    return t, meta


def _patch_result_parts(patch: Any) -> tuple[np.ndarray, dict[str, Any]]:
    if hasattr(patch, "stack") and hasattr(patch, "meta"):
        return patch.stack, dict(patch.meta)
    stack, meta, _scl_patch = patch
    return stack, dict(meta)


def _torch_tensor_from_np(arr: np.ndarray) -> torch.Tensor:
    try:
        return torch.from_numpy(arr)
    except RuntimeError as exc:
        if "Numpy is not available" not in str(exc):
            raise
        return torch.tensor(arr.tolist(), dtype=torch.float32)


def _temporal_s2_specs(in_cfg: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = row.get("temporal_s2") or in_cfg.get("temporal_s2")
    if isinstance(raw, Mapping):
        base = _s2_params_with_profile_defaults(in_cfg, row)
        out: dict[str, dict[str, Any]] = {}
        for label in ("t0", "t1", "t2"):
            slice_cfg = raw.get(label)
            if not isinstance(slice_cfg, Mapping):
                continue
            params = dict(base)
            params.update(slice_cfg)
            if row.get(f"scene_id_{label}") is not None:
                params["scene_id"] = row[f"scene_id_{label}"]
            out[label] = params
        return out

    profile_defaults = profile_input_defaults(_analysis_profile(in_cfg, row))
    labels = tuple(profile_defaults.get("temporal_slices") or ("t1",))
    if labels == ("t1",) and not any(row.get(f"scene_id_{label}") for label in ("t0", "t1", "t2")):
        return {}
    base = _s2_params_with_profile_defaults(in_cfg, row)
    dt = str(base.get("datetime") or _default_datetime_interval(int(profile_defaults["datetime_window_days"])))
    out = {}
    for label in labels:
        params = dict(base)
        params["datetime"] = _previous_datetime_interval(dt, int(profile_defaults["datetime_window_days"])) if label == "t0" else dt
        if row.get(f"scene_id_{label}") is not None:
            params["scene_id"] = row[f"scene_id_{label}"]
        out[label] = params
    return out


def _load_temporal_stac(
    device: torch.device,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, tuple[torch.Tensor, dict[str, Any]]]:
    out: dict[str, tuple[torch.Tensor, dict[str, Any]]] = {}
    for label, params in _temporal_s2_specs(in_cfg, row).items():
        out[label] = _stac_s12_tensor_from_params(device, params, temporal_slice=label)
    return out


def _s2_tensor(
    *,
    device: torch.device,
    mode: str,
    batch_size: int,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
    shared_stac: tuple[torch.Tensor, dict[str, Any]] | None = None,
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
        if shared_stac is not None:
            return shared_stac[0], shared_stac[1]
        t, meta = _stac_s12_tensor(device, in_cfg, row)
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
    shared_stac: tuple[torch.Tensor, dict[str, Any]] | None = None,
) -> tuple[torch.Tensor, dict[str, Any] | None]:
    mod_u = mod.strip()
    block = per_mod.get(mod_u) or per_mod.get(mod_u.upper()) or {}
    bs = int(row.get("batch_size") or block.get("batch_size") or in_cfg.get("batch_size", 1))
    if _is_rgb_modality(mod_u):
        mode = str(
            row.get("rgb_mode")
            or block.get("rgb_mode")
            or block.get("mode")
            or in_cfg.get("rgb_mode")
            or in_cfg.get("mode", "random")
        ).lower()
        if mode == "s2_rgb":
            if bs != 1:
                raise ValueError("rgb_mode=s2_rgb currently supports batch_size=1")
            if shared_stac is None:
                t12, _meta = _stac_s12_tensor(device, in_cfg, row)
            else:
                t12 = shared_stac[0]
            return _rgb_from_s12_reflectance(t12), None
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
        return _s2_tensor(
            device=device,
            mode=mode,
            batch_size=bs,
            in_cfg=in_cfg,
            row=row,
            shared_stac=shared_stac,
        )
    raise NotImplementedError(f"Auto-inputs not implemented for modality {mod_u!r} (extend inputs_build.py).")


def _batch_row_needs_shared_stac_stack(
    modalities: list[str],
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
    per_mod: Mapping[str, Any],
) -> bool:
    for mod in modalities:
        mod_u = mod.strip()
        block = per_mod.get(mod_u) or per_mod.get(mod_u.upper()) or {}
        if _is_s2l2a_modality(mod_u):
            m = str(
                row.get("s2_mode")
                or block.get("s2_mode")
                or block.get("mode")
                or in_cfg.get("s2_mode")
                or "random"
            ).lower()
            if m == "stac":
                return True
        if _is_rgb_modality(mod_u):
            m = str(
                row.get("rgb_mode")
                or block.get("rgb_mode")
                or block.get("mode")
                or in_cfg.get("rgb_mode")
                or in_cfg.get("mode", "random")
            ).lower()
            if m == "s2_rgb":
                return True
    return False


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
    shared_stac: tuple[torch.Tensor, dict[str, Any]] | None = None
    temporal_stac: dict[str, tuple[torch.Tensor, dict[str, Any]]] = {}
    if _batch_row_needs_shared_stac_stack(modalities, in_cfg, row, per_mod):
        temporal_stac = _load_temporal_stac(device, in_cfg, row)
        if temporal_stac:
            active_label = "t1" if "t1" in temporal_stac else sorted(temporal_stac.keys())[-1]
            shared_stac = temporal_stac[active_label]
        else:
            shared_stac = _stac_s12_tensor(device, in_cfg, row)

    for mod in modalities:
        if not isinstance(mod, str):
            raise ValueError("config.modalities entries must be strings for this runner")
        tensor, s2_meta = _tensor_for_modality(
            mod,
            cfg=cfg,
            device=device,
            in_cfg=in_cfg,
            row=row,
            per_mod=per_mod,
            shared_stac=shared_stac,
        )
        out[mod] = tensor
        if s2_meta is not None:
            aux["s2_stac"] = s2_meta
            aux["s2_stac_modality_key"] = mod
    if shared_stac is not None and "s2_stac" not in aux:
        aux["s2_stac"] = shared_stac[1]
        aux["s2_stac_modality_key"] = "RGB(s2_rgb)"
    if temporal_stac:
        aux["temporal_s2_stac"] = {label: meta for label, (_tensor, meta) in temporal_stac.items()}
        aux["scene_provenance"] = {
            label: {
                "item_id": meta.get("stac_item_id"),
                "datetime": meta.get("stac_datetime"),
                "cloud_pct": meta.get("eo_cloud_cover"),
                "scene_id_requested": meta.get("scene_id_requested"),
            }
            for label, (_tensor, meta) in temporal_stac.items()
        }
    try:
        s2p = stac_s2_params_from_cfg(in_cfg, row)
        if s2p.get("lat") is not None and s2p.get("lon") is not None:
            aux["request_wgs84"] = {"latitude": float(s2p["lat"]), "longitude": float(s2p["lon"])}
    except Exception:
        pass
    return out, aux
