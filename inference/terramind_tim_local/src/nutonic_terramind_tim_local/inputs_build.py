"""Build per-modality input tensors for TerraMind TiM (no TerraTorch import)."""

from __future__ import annotations

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


def _stac_s12_tensor(
    device: torch.device,
    in_cfg: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[torch.Tensor, dict[str, Any]]:
    """One STAC read → ``(1,12,H,W)`` float tensor on ``device`` + STAC metadata."""
    s2 = stac_s2_params_from_cfg(in_cfg, row)
    if s2.get("lat") is None or s2.get("lon") is None:
        raise ValueError("STAC S2 requires lat/lon in inputs.s2, inputs root, or batch row")
    lat = float(s2["lat"])
    lon = float(s2["lon"])
    dt = str(s2.get("datetime") or in_cfg.get("datetime") or "").strip()
    if not dt:
        raise ValueError("inputs.s2.datetime (or inputs.datetime / batch row) is required for STAC S2")
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
    if _batch_row_needs_shared_stac_stack(modalities, in_cfg, row, per_mod):
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
    return out, aux
