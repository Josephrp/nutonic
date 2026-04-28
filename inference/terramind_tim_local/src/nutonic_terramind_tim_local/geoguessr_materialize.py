"""GeoGuessr S2-compatible batch: TiM JSON export + **materialized previews for every TiM key**.

For each batch row, ``<output-dir>/<map_id>/materialized/`` contains:

- **``coords``** — ``coords_decoded.json`` (tokenizer ``decode_text``), NaNs JSON-safe.
- **``tok_*``** — ``{key}_decoded.png`` via ``model.tokenizer[key].decode_tokens`` when available;
  LULC / NDVI also get modality-specific previews (argmax palette / grayscale stretch).
- **``untok_*``** — ``{key}_tensor_preview.png`` from the raw ``tensor`` block (RGB or S2-style false color).
- **``tim_shapes.json``** — compact dtype/shape (and channel count) for every sub-tensor in the TiM dict.

Run from ``inference/terramind_tim_local`` with ``--extra s2``:

.. code-block:: bash

   uv run --directory inference/terramind_tim_local python -m nutonic_terramind_tim_local.geoguessr_materialize \\
     --output-dir ../../data/downloads/tim_geoguessr_large_materialized

Default config: ``config.geoguessr_live_3row_s2_compatible_large.yaml`` (``terramind_v1_large_tim``,
``pretrained: true``).
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

try:
    from terratorch import BACKBONE_REGISTRY
except ModuleNotFoundError:  # pragma: no cover - optional heavy dependency
    BACKBONE_REGISTRY = None

from nutonic_terramind_tim_local.capture import attach_tim_sampler_capture
from nutonic_terramind_tim_local.inputs_build import _build_inputs, load_run_config
from nutonic_terramind_tim_local.terramind_patches import apply_terramind_tim_runtime_hotfixes

try:
    from nutonic_terramind_tim_local.run import _export_row, append_jsonl, write_json
except ModuleNotFoundError as exc:  # pragma: no cover - optional TerraTorch path
    if exc.name != "terratorch":
        raise
    _export_row = None
    append_jsonl = None
    write_json = None

if BACKBONE_REGISTRY is not None:
    apply_terramind_tim_runtime_hotfixes()

# Ten-class legend for argmax on (1, 10, H, W) LULC decode (preview only).
def _safe_stem(tim_key: str) -> str:
    return tim_key.replace("@", "_at_").replace("/", "_").replace("\\", "_")


def _json_default(o: Any) -> Any:
    if isinstance(o, float) and (o != o):
        return None
    raise TypeError


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


def _tensor_to_np(tensor: torch.Tensor, dtype: Any | None = None) -> np.ndarray:
    try:
        arr = tensor.numpy()
    except RuntimeError as exc:
        if "Numpy is not available" not in str(exc):
            raise
        arr = np.array(tensor.tolist())
    if dtype is not None:
        return arr.astype(dtype)
    return arr


def _save_lulc_argmax_png(dec: torch.Tensor, path: Path) -> None:
    dec = dec.detach().float().cpu()
    if dec.ndim != 4:
        raise ValueError(f"Unexpected LULC decode shape {tuple(dec.shape)}")
    _, c, _, _ = dec.shape
    if c >= 10:
        labels = _tensor_to_np(dec.argmax(dim=1)[0], np.int64)
    elif c == 1:
        labels = _tensor_to_np(dec[0, 0].round().long().clamp(0, 9), np.int64)
    else:
        x = _tensor_to_np(dec[0, : min(3, c)])
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


def _tensor_bchw_to_rgb_u8(t_bchw: torch.Tensor) -> np.ndarray:
    """
    Map ``(B,C,H,W)`` batch item 0 to uint8 RGB ``(H,W,3)``.

    - **12 channels** — treat as Sentinel-2 L2A order: use RED/GREEN/BLUE = bands 3,2,1 (0-based).
    - **3+ channels** — first three, min–max normalized jointly.
    - **2 channels** — R,G and B=0.
    - **1 channel** — grayscale replicated to RGB.
    """
    t = t_bchw.detach().float().cpu()
    if t.ndim != 4:
        raise ValueError(f"Expected (B,C,H,W), got {tuple(t.shape)}")
    x = _tensor_to_np(t[0])
    c = x.shape[0]
    if c >= 12:
        red_i, green_i, blue_i = 3, 2, 1
        x3 = np.stack([x[red_i], x[green_i], x[blue_i]], axis=0)
    elif c >= 3:
        x3 = x[:3]
    elif c == 2:
        x3 = np.concatenate([x, np.zeros((1, x.shape[1], x.shape[2]), dtype=x.dtype)], axis=0)
    elif c == 1:
        x3 = np.repeat(x, 3, axis=0)
    else:
        raise ValueError(f"Need C>=1, got C={c}")
    lo, hi = float(x3.min()), float(x3.max())
    if hi <= lo:
        return np.zeros((x3.shape[1], x3.shape[2], 3), dtype=np.uint8)
    xn = (x3 - lo) / (hi - lo)
    return (np.clip(xn.transpose(1, 2, 0), 0.0, 1.0) * 255.0).astype(np.uint8)


def _save_bchw_preview_png(t_bchw: torch.Tensor, path: Path) -> None:
    rgb = _tensor_bchw_to_rgb_u8(t_bchw)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path)


def _save_generic_decoded_preview(dec: torch.Tensor, path: Path) -> None:
    """Single-channel percentile stretch or multi-channel RGB from ``decode_tokens`` output."""
    dec = dec.detach().float().cpu()
    if dec.ndim == 4:
        _save_bchw_preview_png(dec, path)
        return
    if dec.ndim == 3:
        v = _tensor_to_np(dec[0])
        lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
        if hi <= lo:
            u8 = np.zeros_like(v, dtype=np.uint8)
        else:
            u8 = (np.clip((v - lo) / (hi - lo), 0.0, 1.0) * 255.0).astype(np.uint8)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(u8, mode="L").save(path)
        return
    raise ValueError(f"Unsupported decode tensor rank {dec.ndim}")


def _tim_dict_tensor_summary(tim: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, block in tim.items():
        if not isinstance(block, dict):
            out[k] = type(block).__name__
            continue
        sub: dict[str, Any] = {}
        for sk, sv in block.items():
            if isinstance(sv, torch.Tensor):
                sub[sk] = {"dtype": str(sv.dtype), "shape": list(sv.shape)}
            else:
                sub[sk] = type(sv).__name__
        out[k] = sub
    return out


def _save_ndvi_preview_png(dec: torch.Tensor, path: Path) -> None:
    dec = dec.detach().float().cpu()
    if dec.ndim == 4:
        v = _tensor_to_np(dec[0].mean(dim=0))
    elif dec.ndim == 3:
        v = _tensor_to_np(dec[0])
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
    analysis_profile: str = "brief_only",
    profile_analytics: Mapping[str, Any] | None = None,
    inputs_aux: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``materialized/`` under ``row_out`` (e.g. ``.../poi_0013``). Returns a small manifest."""
    row_out = Path(row_out)
    mat = row_out / "materialized"
    mat.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"assets": []}
    tok = getattr(model, "tokenizer", None)
    mod_dev = next(model.parameters()).device

    shapes_path = mat / "tim_shapes.json"
    shapes_path.write_text(json.dumps(_tim_dict_tensor_summary(tim), indent=2) + "\n", encoding="utf-8")
    manifest["assets"].append({"tim_key": "_summary", "kind": "tim_shapes_json", "path": str(shapes_path.resolve())})

    if not isinstance(tim, Mapping) or not tim:
        return manifest

    for tim_key in sorted(tim.keys()):
        block = tim[tim_key]
        stem = _safe_stem(tim_key)

        if tim_key == "coords":
            if tok is None or "coords" not in tok or not isinstance(block, dict):
                manifest["assets"].append({"tim_key": tim_key, "kind": "skip", "reason": "no_coords_tokenizer_or_block"})
                continue
            try:
                decoded = tok["coords"].decode_text({"coords": dict(block)})
                cpath = mat / f"{stem}_decoded.json"
                cpath.write_text(
                    json.dumps({"decoded_lon_lat_pairs": decoded}, indent=2, default=_json_default) + "\n",
                    encoding="utf-8",
                )
                manifest["assets"].append({"tim_key": tim_key, "kind": "coords_json", "path": str(cpath.resolve())})
            except Exception as exc:  # noqa: BLE001
                manifest["assets"].append({"tim_key": tim_key, "error": str(exc)[:500]})
            continue

        if not isinstance(block, dict):
            manifest["assets"].append({"tim_key": tim_key, "kind": "skip", "reason": "block_not_dict"})
            continue

        if tim_key.startswith("untok_"):
            raw = block.get("tensor")
            if isinstance(raw, torch.Tensor) and raw.ndim == 4:
                try:
                    p = mat / f"{stem}_tensor_preview.png"
                    _save_bchw_preview_png(raw, p)
                    manifest["assets"].append(
                        {"tim_key": tim_key, "kind": "untok_tensor_rgb_preview", "path": str(p.resolve())}
                    )
                except Exception as exc:  # noqa: BLE001
                    manifest["assets"].append({"tim_key": tim_key, "error": str(exc)[:500]})
            else:
                manifest["assets"].append(
                    {"tim_key": tim_key, "kind": "skip", "reason": "no_bchw_tensor", "tensor_ndim": getattr(raw, "ndim", None)}
                )
            continue

        if tim_key.startswith("tok_"):
            if tok is None or tim_key not in tok:
                manifest["assets"].append({"tim_key": tim_key, "kind": "skip", "reason": "no_tokenizer_entry"})
                continue
            tok_mod = tok[tim_key]
            if not hasattr(tok_mod, "decode_tokens"):
                manifest["assets"].append({"tim_key": tim_key, "kind": "skip", "reason": "no_decode_tokens"})
                continue
            if "tensor" not in block:
                manifest["assets"].append({"tim_key": tim_key, "kind": "skip", "reason": "no_tensor"})
                continue
            try:
                ids_bhw = _ids_bhw_from_block(block, mod_dev)
                dec = _decode_tokens_safe(tok_mod, ids_bhw)
            except Exception as exc:  # noqa: BLE001
                manifest["assets"].append({"tim_key": tim_key, "error": str(exc)[:500]})
                continue

            try:
                p_generic = mat / f"{stem}_decoded.png"
                _save_generic_decoded_preview(dec, p_generic)
                manifest["assets"].append(
                    {"tim_key": tim_key, "kind": "tok_decoded_preview", "path": str(p_generic.resolve())}
                )
                if "lulc" in tim_key.lower():
                    p2 = mat / f"{stem}_lulc_argmax_rgb.png"
                    _save_lulc_argmax_png(dec, p2)
                    manifest["assets"].append(
                        {"tim_key": tim_key, "kind": "lulc_argmax_rgb", "path": str(p2.resolve())}
                    )
                if "ndvi" in tim_key.lower():
                    p3 = mat / f"{stem}_ndvi_percentile_gray.png"
                    _save_ndvi_preview_png(dec, p3)
                    manifest["assets"].append(
                        {"tim_key": tim_key, "kind": "ndvi_preview_gray", "path": str(p3.resolve())}
                    )
            except Exception as exc:  # noqa: BLE001
                manifest["assets"].append({"tim_key": tim_key, "decode_ok": True, "write_error": str(exc)[:500]})
            continue

        raw = block.get("tensor")
        if isinstance(raw, torch.Tensor) and raw.ndim == 4:
            try:
                p = mat / f"{stem}_tensor_preview.png"
                _save_bchw_preview_png(raw, p)
                manifest["assets"].append(
                    {"tim_key": tim_key, "kind": "generic_bchw_preview", "path": str(p.resolve())}
                )
            except Exception as exc:  # noqa: BLE001
                manifest["assets"].append({"tim_key": tim_key, "error": str(exc)[:500]})
        else:
            manifest["assets"].append(
                {"tim_key": tim_key, "kind": "skip", "reason": "no_materializer_for_block_shape"}
            )

    manifest["profile_artifact_index"] = _write_profile_artifact_index(
        row_out,
        analysis_profile=analysis_profile,
        manifest=manifest,
        profile_analytics=profile_analytics or {},
        inputs_aux=inputs_aux or {},
    )
    return manifest


def _write_profile_artifact_index(
    row_out: Path,
    *,
    analysis_profile: str,
    manifest: Mapping[str, Any],
    profile_analytics: Mapping[str, Any],
    inputs_aux: Mapping[str, Any],
) -> dict[str, Any]:
    row_out = Path(row_out)
    mat = row_out / "materialized"
    scene_provenance = _scene_provenance_from_aux(inputs_aux)
    assets = _indexable_assets(manifest)
    generated: list[dict[str, Any]] = []

    if analysis_profile == "oceanscout_ship_detection":
        generated.extend(_write_oceanscout_contract_artifacts(mat, profile_analytics, scene_provenance))

    overlays = _profile_overlay_descriptors(analysis_profile, assets, generated)
    index_payload = {
        "schema_version": "nutonic.pro.profile_artifact_index.v1",
        "analysis_profile": analysis_profile,
        "scene_provenance": scene_provenance,
        "assets": assets + generated,
        "overlays": overlays,
        "claim_safety": _profile_claim_safety(analysis_profile),
    }
    index_path = mat / "profile_artifact_index.json"
    index_path.write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "kind": "profile_artifact_index",
        "path": str(index_path.resolve()),
        "overlay_count": len(overlays),
    }


def _indexable_assets(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for asset in manifest.get("assets") or []:
        if not isinstance(asset, Mapping):
            continue
        path = asset.get("path")
        if not isinstance(path, str):
            continue
        out.append(
            {
                "artifact_id": Path(path).stem,
                "kind": asset.get("kind"),
                "tim_key": asset.get("tim_key"),
                "path": path,
                "mime_type": _mime_for_path(Path(path)),
            }
        )
    return out


def _write_oceanscout_contract_artifacts(
    mat: Path,
    profile_analytics: Mapping[str, Any],
    scene_provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observation_coverage = profile_analytics.get("observation_coverage")
    if not isinstance(observation_coverage, Mapping):
        observation_coverage = {
            "valid_observation_count": 0,
            "cloud_masked_count": 0,
            "source": "not_available",
        }
    candidates = profile_analytics.get("vessel_candidates")
    if not isinstance(candidates, list):
        candidates = []
    overlay = {
        "type": "FeatureCollection",
        "name": "oceanscout_vessel_overlay",
        "features": [_candidate_feature(candidate) for candidate in candidates if isinstance(candidate, Mapping)],
        "properties": {
            "scene_provenance": scene_provenance,
            "base_model_color": "green",
            "tim_enhanced_color": "blue",
            "limitations": _profile_claim_safety("oceanscout_ship_detection")["limitations"],
        },
    }
    paths = [
        ("observation_coverage", "json", observation_coverage),
        ("vessel_candidates", "json", {"candidates": candidates}),
        ("vessel_overlay", "geojson", overlay),
    ]
    generated: list[dict[str, Any]] = []
    for artifact_id, ext, payload in paths:
        path = mat / f"{artifact_id}.{ext}"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        generated.append(
            {
                "artifact_id": artifact_id,
                "kind": artifact_id,
                "path": str(path.resolve()),
                "mime_type": _mime_for_path(path),
            }
        )
    return generated


def _candidate_feature(candidate: Mapping[str, Any]) -> dict[str, Any]:
    lat = candidate.get("center_lat")
    lon = candidate.get("center_lon")
    geometry = None
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        geometry = {"type": "Point", "coordinates": [float(lon), float(lat)]}
    return {"type": "Feature", "properties": dict(candidate), "geometry": geometry}


def _profile_overlay_descriptors(
    analysis_profile: str,
    assets: list[dict[str, Any]],
    generated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    png_assets = [asset for asset in assets if str(asset.get("mime_type")) == "image/png"]
    lulc = next((asset for asset in png_assets if "lulc" in str(asset.get("artifact_id", "")).lower()), None)
    ndvi = next((asset for asset in png_assets if "ndvi" in str(asset.get("artifact_id", "")).lower()), None)
    first_png = png_assets[0] if png_assets else None
    if analysis_profile == "wildfire":
        asset = ndvi or first_png
        return [_overlay_descriptor("burn_change_heatmap", asset)] if asset else []
    if analysis_profile == "land_use_change":
        asset = lulc or first_png
        return [_overlay_descriptor("land_transition_palette", asset)] if asset else []
    if analysis_profile == "flood_pulse":
        asset = ndvi or first_png
        return [_overlay_descriptor("water_change_heatmap", asset)] if asset else []
    if analysis_profile == "oceanscout_ship_detection":
        overlay = next((asset for asset in generated if asset.get("artifact_id") == "vessel_overlay"), None)
        return [_overlay_descriptor("vessel_candidate_overlay", overlay)] if overlay else []
    return []


def _overlay_descriptor(kind: str, asset: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "artifact_id": asset.get("artifact_id") if isinstance(asset, Mapping) else None,
        "path": asset.get("path") if isinstance(asset, Mapping) else None,
        "mime_type": asset.get("mime_type") if isinstance(asset, Mapping) else None,
    }


def _scene_provenance_from_aux(inputs_aux: Mapping[str, Any]) -> dict[str, Any]:
    scene_provenance = inputs_aux.get("scene_provenance")
    if isinstance(scene_provenance, Mapping):
        return dict(scene_provenance)
    s2 = inputs_aux.get("s2_stac")
    if isinstance(s2, Mapping) and s2.get("stac_item_id"):
        return {
            "t1": {
                "item_id": s2.get("stac_item_id"),
                "datetime": s2.get("stac_datetime"),
                "cloud_pct": s2.get("eo_cloud_cover"),
                "scene_id_requested": s2.get("scene_id_requested"),
            }
        }
    return {}


def _profile_claim_safety(analysis_profile: str) -> dict[str, Any]:
    if analysis_profile == "oceanscout_ship_detection":
        return {
            "evidence_level": "screening_signal",
            "limitations": [
                "Candidate overlays are model-support signals, not proof of vessel identity or illegal activity.",
                "Observation coverage must be displayed before claim-oriented summaries.",
            ],
        }
    return {
        "evidence_level": "screening_signal",
        "limitations": ["Profile overlays require source-scene review before operational use."],
    }


def _mime_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".geojson":
        return "application/geo+json"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def run_geoguessr_batch_with_materialize(cfg: Mapping[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device(str(cfg.get("device", "cpu")))
    if BACKBONE_REGISTRY is None or _export_row is None:
        raise ImportError("geoguessr materialization requires terratorch")
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
            analysis_profile=str(row.get("analysis_profile") or cfg.get("analysis_profile") or "brief_only"),
            inputs_aux=inputs_aux,
        )
        profile_analytics = export_row.get("profile_analytics")
        export_row["materialized"] = materialize_tim_row(
            model,
            tim_raw,
            output_dir / mid,
            analysis_profile=str(export_row.get("analysis_profile") or "brief_only"),
            profile_analytics=profile_analytics if isinstance(profile_analytics, Mapping) else None,
            inputs_aux=inputs_aux,
        )
        out_rows.append(export_row)
    return out_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GeoGuessr S2-compatible TiM batch + per-POI materialized previews for every TiM output key.",
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

    if write_json is None or append_jsonl is None:
        raise ImportError("geoguessr materialization requires terratorch")
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
