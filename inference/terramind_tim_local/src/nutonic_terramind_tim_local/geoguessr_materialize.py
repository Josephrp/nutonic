"""GeoGuessr S2-compatible batch: TiM JSON export + decoded LULC/NDVI PNGs per ``map_id``.

Run from ``inference/terramind_tim_local`` (same cwd as other configs), with ``--extra s2``:

.. code-block:: bash

   uv run --directory inference/terramind_tim_local python -m nutonic_terramind_tim_local.geoguessr_materialize \\
     --output-dir ../../data/downloads/tim_geoguessr_large_materialized

Default config: ``config.geoguessr_live_3row_s2_compatible_large.yaml`` (``terramind_v1_large_tim``,
``pretrained: true``). Each POI row gets ``<output-dir>/<map_id>/materialized/`` with raster
previews from ``tokenizer[tok_*].decode_tokens`` (B×H×W token grid reshaped from TiM ``tensor``).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from PIL import Image
from terratorch import BACKBONE_REGISTRY

from nutonic_terramind_tim_local.capture import attach_tim_sampler_capture
from nutonic_terramind_tim_local.inputs_build import _build_inputs, load_run_config
from nutonic_terramind_tim_local.run import _export_row, append_jsonl, write_json
from nutonic_terramind_tim_local.terramind_patches import apply_terramind_coord_decode_hotfix

apply_terramind_coord_decode_hotfix()

# Ten-class legend for argmax on (1, 10, H, W) LULC decode (preview only).
LULC_PALETTE_RGB = np.array(
    [
        [0, 0, 0],
        [0, 0, 255],
        [34, 139, 34],
        [144, 238, 144],
        [255, 215, 0],
        [255, 0, 0],
        [210, 180, 140],
        [255, 255, 255],
        [128, 128, 128],
        [154, 205, 50],
    ],
    dtype=np.uint8,
)


def _ids_bhw_from_block(block: Mapping[str, Any], device: torch.device) -> torch.Tensor:
    """TiM ``tensor`` (B, P) with P = H×W patch tokens → (B, H, W) ``long`` indices."""
    raw = block["tensor"]
    if not isinstance(raw, torch.Tensor):
        raise TypeError("block['tensor'] must be a torch.Tensor")
    x = torch.nan_to_num(raw.detach().float(), nan=0.0, posinf=0.0, neginf=0.0).to(device)
    if x.ndim == 1:
        x = x.unsqueeze(0)
    if x.ndim != 2:
        raise ValueError(f"Expected token tensor (B, P), got {tuple(x.shape)}")
    _b, p = x.shape
    s = int(math.isqrt(int(p)))
    if s * s != p:
        raise ValueError(f"Token count {p} is not a perfect square")
    # FSQ composite indices must be stable integers on the tokenizer device.
    x = torch.floor(x + 0.5).clamp(min=0.0)
    return x.to(dtype=torch.int64).view(_b, s, s)


def _codebook_upper(tok_mod: Any) -> int | None:
    """
    Max valid discrete index for clamping before ``decode_tokens``.

    FSQ tokenizers store ``codebook_size`` as a hyphen string (e.g. ``\"7-5-5-5-5\"``);
    ``int()`` on that string raises — use the quantizer's level product instead.
    """
    cb = getattr(tok_mod, "codebook_size", None)
    if isinstance(cb, str) and "-" in cb:
        q = getattr(tok_mod, "quantize", None)
        if q is not None and hasattr(q, "_levels"):
            return int(q._levels.prod().item())
        return None
    if cb is None:
        return None
    try:
        return int(cb)
    except (TypeError, ValueError):
        return None


def _decode_tokens_safe(tok_mod: Any, ids_bhw: torch.Tensor) -> torch.Tensor:
    cb = _codebook_upper(tok_mod)
    x = ids_bhw
    if cb is not None:
        x = x.clamp(min=0, max=max(cb - 1, 0))
    return tok_mod.decode_tokens(x)


def _save_lulc_argmax_png(dec: torch.Tensor, path: Path) -> None:
    dec = dec.detach().float().cpu()
    if dec.ndim != 4:
        raise ValueError(f"Unexpected LULC decode shape {tuple(dec.shape)}")
    _, c, _, _ = dec.shape
    if c >= 10:
        labels = dec.argmax(dim=1)[0].numpy().astype(np.int64)
    elif c == 1:
        labels = dec[0, 0].round().long().clamp(0, 9).numpy().astype(np.int64)
    else:
        x = dec[0, : min(3, c)].numpy()
        lo, hi = float(x.min()), float(x.max())
        if hi <= lo:
            rgb = np.zeros((x.shape[1], x.shape[2], 3), dtype=np.uint8)
        else:
            x3 = np.zeros((3, x.shape[1], x.shape[2]), dtype=np.float32)
            x3[:c] = x
            xn = (x3 - lo) / (hi - lo)
            rgb = (np.clip(xn.transpose(1, 2, 0), 0.0, 1.0) * 255.0).astype(np.uint8)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb, mode="RGB").save(path)
        return
    labels = np.clip(labels, 0, LULC_PALETTE_RGB.shape[0] - 1)
    rgb = LULC_PALETTE_RGB[labels]
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path)


def _save_untok_rgb_preview(block: Mapping[str, Any], path: Path) -> None:
    """Save first 3 channels of ``untok_*`` reflectance stack (rough preview, not TiM decode)."""
    raw = block.get("tensor")
    if not isinstance(raw, torch.Tensor) or raw.ndim != 4 or raw.shape[1] < 3:
        raise ValueError("untok tensor must be (B, C>=3, H, W)")
    t = raw.detach().float().cpu()[0, :3].numpy()
    lo, hi = float(t.min()), float(t.max())
    if hi <= lo:
        rgb = np.zeros((t.shape[1], t.shape[2], 3), dtype=np.uint8)
    else:
        tn = (t - lo) / (hi - lo)
        rgb = (np.clip(tn.transpose(1, 2, 0), 0.0, 1.0) * 255.0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path)


def _save_ndvi_preview_png(dec: torch.Tensor, path: Path) -> None:
    dec = dec.detach().float().cpu()
    if dec.ndim == 4:
        v = dec[0].mean(dim=0).numpy()
    elif dec.ndim == 3:
        v = dec[0].numpy()
    else:
        raise ValueError(f"Unexpected NDVI decode shape {tuple(dec.shape)}")
    lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
    if hi <= lo:
        u8 = np.zeros_like(v, dtype=np.uint8)
    else:
        vn = np.clip((v - lo) / (hi - lo), 0.0, 1.0)
        u8 = (vn * 255.0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(u8, mode="L").save(path)


def materialize_tim_row(
    model: torch.nn.Module,
    tim: Mapping[str, Any],
    row_out: Path,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Write ``materialized/`` under ``row_out`` (e.g. ``.../poi_0013``). Returns a small manifest."""
    row_out = Path(row_out)
    mat = row_out / "materialized"
    mat.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"assets": []}
    tok = getattr(model, "tokenizer", None)
    if tok is None:
        return manifest

    mod_dev = next(model.parameters()).device

    for tim_key, block in tim.items():
        if not tim_key.startswith("tok_") or not isinstance(block, dict) or "tensor" not in block:
            continue
        if tim_key not in tok:
            continue
        try:
            ids_bhw = _ids_bhw_from_block(block, mod_dev)
            dec = _decode_tokens_safe(tok[tim_key], ids_bhw)
        except Exception as exc:  # noqa: BLE001
            manifest["assets"].append({"tim_key": tim_key, "error": str(exc)[:500]})
            continue

        try:
            if "lulc" in tim_key.lower():
                p = mat / "lulc_decoded_argmax_rgb.png"
                _save_lulc_argmax_png(dec, p)
                manifest["assets"].append(
                    {"tim_key": tim_key, "kind": "lulc_argmax_rgb", "path": str(p.resolve())}
                )
            elif "ndvi" in tim_key.lower():
                p = mat / "ndvi_decoded_preview.png"
                _save_ndvi_preview_png(dec, p)
                manifest["assets"].append(
                    {"tim_key": tim_key, "kind": "ndvi_preview_gray", "path": str(p.resolve())}
                )
        except Exception as exc:  # noqa: BLE001
            manifest["assets"].append({"tim_key": tim_key, "decode_ok": True, "write_error": str(exc)[:500]})

    # Optional input echo when TiM token decode failed (encoder-side RGB reflectance).
    ut = tim.get("untok_sen2rgb@224")
    if isinstance(ut, dict) and "tensor" in ut:
        try:
            p = mat / "untok_sen2rgb_input_preview.png"
            _save_untok_rgb_preview(ut, p)
            manifest["assets"].append(
                {"tim_key": "untok_sen2rgb@224", "kind": "input_rgb_preview", "path": str(p.resolve())}
            )
        except Exception as exc:  # noqa: BLE001
            manifest["assets"].append({"tim_key": "untok_sen2rgb@224", "error": str(exc)[:300]})

    if isinstance(tim.get("coords"), dict) and "coords" in tok:
        try:
            decoded = tok["coords"].decode_text({"coords": dict(tim["coords"])})
            cpath = mat / "coords_decoded.json"
            cpath.write_text(
                json.dumps({"decoded_lon_lat_pairs": decoded}, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest["assets"].append({"tim_key": "coords", "kind": "json", "path": str(cpath.resolve())})
        except Exception as exc:  # noqa: BLE001
            manifest["assets"].append({"tim_key": "coords", "error": str(exc)[:300]})

    return manifest


def run_geoguessr_batch_with_materialize(cfg: Mapping[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

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

    rows_cfg = cfg.get("batch")
    if not isinstance(rows_cfg, list) or not rows_cfg:
        raise ValueError("config.batch must be a non-empty list")

    out_rows: list[dict[str, Any]] = []
    for row in rows_cfg:
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
        export_row = _export_row(
            model,
            enc_layers,
            tim_raw,
            cfg,
            map_id=mid,
            location_id=lid,
            inputs_aux=inputs_aux,
        )
        export_row["materialized"] = materialize_tim_row(model, tim_raw, output_dir / mid, device=device)
        out_rows.append(export_row)
    return out_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GeoGuessr S2-compatible TiM batch + per-POI materialized LULC/NDVI PNGs.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.geoguessr_live_3row_s2_compatible_large.yaml"),
        help="YAML config (cwd: inference/terramind_tim_local). Default: large pretrained TerraMind.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Writes tim_run.json, tim_export.jsonl, and <map_id>/materialized/*",
    )
    parser.add_argument("--jsonl-name", type=str, default="tim_export.jsonl")
    ns = parser.parse_args(argv)

    cfg_path = ns.config.resolve()
    if not cfg_path.is_file():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        return 2

    cfg = load_run_config(cfg_path)
    out_dir = ns.output_dir.resolve()
    rows = run_geoguessr_batch_with_materialize(cfg, out_dir)

    write_json(out_dir / "tim_run.json", {"runs": rows})
    jsonl = out_dir / ns.jsonl_name
    if jsonl.exists():
        jsonl.unlink()
    for row in rows:
        append_jsonl(jsonl, row)

    print(
        json.dumps(
            {"tim_run": str((out_dir / "tim_run.json").resolve()), "tim_jsonl": str(jsonl.resolve())},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
