import os
import gc
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import torch
import torch.nn.functional as F
import rioxarray as rxr

from terratorch.registry import FULL_MODEL_REGISTRY


DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
TILE_SIZE = 224

# Supported per TerraMind notebooks
SUPPORTED_MODALITIES = ["S2L2A", "S1GRD", "S1RTC", "DEM", "LULC", "NDVI"]

# Expected channel counts (based on notebooks + common TerraMind setup)
EXPECTED_CHANNELS = {
    "S2L2A": 12,
    "S1GRD": 2,
    "S1RTC": 2,
    "DEM": 1,
    "LULC": 1,   # input is usually one class-id band; output becomes 10 logits -> argmax
    "NDVI": 1,
}

# cache models by (input_mod, tuple(outputs))
_MODEL_CACHE: Dict[Tuple[str, Tuple[str, ...]], torch.nn.Module] = {}


@dataclass
class RunInfo:
    device: str
    input_modality: str
    output_modalities: List[str]
    input_shape: Tuple[int, int, int]
    warnings: List[str]


def _clear_memory():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load_tif(path: str) -> np.ndarray:
    da = rxr.open_rasterio(path)
    arr = da.values  # (C,H,W)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return arr


def _center_crop_chw(x: torch.Tensor, size: int = TILE_SIZE) -> torch.Tensor:
    # x: (B,C,H,W)
    _, _, h, w = x.shape
    if h < size or w < size:
        return x
    top = (h - size) // 2
    left = (w - size) // 2
    return x[:, :, top:top+size, left:left+size]


def _resize_chw(x: torch.Tensor, size: int = TILE_SIZE, mode: str = "bilinear") -> torch.Tensor:
    return F.interpolate(x, size=(size, size), mode=mode, align_corners=False if mode == "bilinear" else None)


def preprocess_to_224(
    arr_chw: np.ndarray,
    modality: str,
    strategy: str = "center_crop_then_resize",
) -> torch.Tensor:
    """
    Returns tensor (1,C,224,224) float32.
    strategy:
      - "resize": always resize to 224
      - "center_crop": crop if larger, error if smaller
      - "center_crop_then_resize": crop if larger else resize up
    """
    if modality not in SUPPORTED_MODALITIES:
        raise ValueError(f"Unsupported modality: {modality}")

    # Channel check (strict; no hacks)
    c_expected = EXPECTED_CHANNELS[modality]
    if arr_chw.shape[0] != c_expected:
        raise ValueError(
            f"{modality} expects {c_expected} band(s), but your TIFF has {arr_chw.shape[0]} band(s)."
        )

    x = torch.from_numpy(arr_chw).unsqueeze(0)  # (1,C,H,W), float32

    # LULC is categorical -> use nearest if resizing
    resize_mode = "nearest" if modality == "LULC" else "bilinear"

    if strategy == "resize":
        x = _resize_chw(x, TILE_SIZE, mode=resize_mode)

    elif strategy == "center_crop":
        if x.shape[-2] < TILE_SIZE or x.shape[-1] < TILE_SIZE:
            raise ValueError(f"Image is smaller than {TILE_SIZE} in at least one dimension; cannot center-crop.")
        x = _center_crop_chw(x, TILE_SIZE)

    elif strategy == "center_crop_then_resize":
        if x.shape[-2] >= TILE_SIZE and x.shape[-1] >= TILE_SIZE:
            x = _center_crop_chw(x, TILE_SIZE)
        else:
            x = _resize_chw(x, TILE_SIZE, mode=resize_mode)

    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return x.contiguous().float()


def build_model(input_modality: str, output_modalities: List[str]) -> torch.nn.Module:
    key = (input_modality, tuple(output_modalities))
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    _clear_memory()

    model = FULL_MODEL_REGISTRY.build(
        "terramind_v1_base_generate",
        modalities=[input_modality],
        output_modalities=output_modalities,
        pretrained=True,
        standardize=True,  # IMPORTANT: matches official notebooks
    ).to(DEVICE).eval()

    _MODEL_CACHE[key] = model
    return model


# ---- Visualization helpers (simple versions of plotting_utils) ----
def s2_to_rgb(x_bchw: torch.Tensor) -> np.ndarray:
    # expects at least 4 bands with S2 ordering like examples (RGB are [3,2,1])
    x = x_bchw[0].detach().cpu()
    rgb = x[[3, 2, 1]].permute(1, 2, 0).numpy()
    # same style as tokenizer notebook: /2000 then clip
    rgb = (rgb / 2000.0).clip(0, 1)
    return rgb


def s1_to_rgb(x_bchw: torch.Tensor) -> np.ndarray:
    # show VV,VH as pseudo-RGB (VV, VH, VV)
    x = x_bchw[0].detach().cpu()
    vv = x[0].numpy()
    vh = x[1].numpy() if x.shape[0] > 1 else vv
    def norm(a):
        p2, p98 = np.percentile(a, (2, 98))
        if (p98 - p2) < 1e-6:
            return np.zeros_like(a)
        return np.clip((a - p2) / (p98 - p2), 0, 1)
    vv_n = norm(vv)
    vh_n = norm(vh)
    rgb = np.stack([vv_n, vh_n, vv_n], axis=-1)
    return rgb


def dem_to_rgb(x_bchw: torch.Tensor) -> np.ndarray:
    x = x_bchw[0, 0].detach().cpu().numpy()
    p2, p98 = np.percentile(x, (2, 98))
    img = np.clip((x - p2) / (p98 - p2 + 1e-6), 0, 1)
    return np.stack([img, img, img], axis=-1)


def ndvi_to_rgb(x_bchw: torch.Tensor) -> np.ndarray:
    x = x_bchw[0, 0].detach().cpu().numpy()
    # NDVI approx [-1,1] -> map to 0..1
    img = (x + 1.0) / 2.0
    img = np.clip(img, 0, 1)
    return np.stack([img, img, img], axis=-1)


def lulc_to_rgb_from_logits_or_labels(x: torch.Tensor) -> np.ndarray:
    """
    If x is (B,10,H,W) logits -> argmax.
    If x is (B,1,H,W) labels -> use directly.
    """
    xb = x.detach().cpu()
    if xb.ndim != 4:
        raise ValueError("Unexpected LULC tensor shape.")
    if xb.shape[1] == 10:
        labels = xb.argmax(dim=1)[0].numpy().astype(np.int32)
    else:
        labels = xb[0, 0].numpy().astype(np.int32)

    # Simple palette (10 classes)
    palette = np.array([
        [0, 0, 0],
        [31, 119, 180],
        [255, 127, 14],
        [44, 160, 44],
        [214, 39, 40],
        [148, 103, 189],
        [140, 86, 75],
        [227, 119, 194],
        [127, 127, 127],
        [188, 189, 34],
    ], dtype=np.uint8)

    labels = np.clip(labels, 0, 9)
    rgb = palette[labels]
    return (rgb / 255.0).astype(np.float32)


def render_modality(mod: str, tensor_bchw: torch.Tensor) -> np.ndarray:
    if mod == "S2L2A":
        return s2_to_rgb(tensor_bchw)
    if mod in ("S1GRD", "S1RTC"):
        return s1_to_rgb(tensor_bchw)
    if mod == "DEM":
        return dem_to_rgb(tensor_bchw)
    if mod == "NDVI":
        return ndvi_to_rgb(tensor_bchw)
    if mod == "LULC":
        return lulc_to_rgb_from_logits_or_labels(tensor_bchw)
    raise ValueError(f"No renderer for modality {mod}")


def run_generation(
    input_tif: str,
    input_modality: str,
    output_modalities: List[str],
    timesteps: int = 10,
    preprocess_strategy: str = "center_crop_then_resize",
) -> Tuple[Dict[str, torch.Tensor], RunInfo]:
    """
    Returns (generated_dict, run_info)
    generated_dict keys = output_modalities, values are tensors (B,C,H,W)
    """
    if input_modality not in SUPPORTED_MODALITIES:
        raise ValueError(f"Unsupported input modality: {input_modality}")

    for m in output_modalities:
        if m not in SUPPORTED_MODALITIES:
            raise ValueError(f"Unsupported output modality: {m}")

    if input_modality in output_modalities:
        raise ValueError("Remove the input modality from outputs (same as notebook).")

    arr = load_tif(input_tif)
    inp = preprocess_to_224(arr, modality=input_modality, strategy=preprocess_strategy).to(DEVICE)

    model = build_model(input_modality, output_modalities)

    warnings = []
    if input_modality == "S1RTC":
        warnings.append("Make sure your SAR really is RTC. If it is GEE S1_GRD, choose S1GRD instead.")

    with torch.no_grad():
        generated = model(inp, verbose=False, timesteps=int(timesteps))

    info = RunInfo(
        device=DEVICE,
        input_modality=input_modality,
        output_modalities=output_modalities,
        input_shape=tuple(arr.shape),
        warnings=warnings,
    )
    return generated, info