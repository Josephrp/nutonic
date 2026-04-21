"""End-to-end per-POI raster fusion, tiling, downsampling, and sample rows."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image

from lfm_vl_sft_dataset.bbox_overlay import write_bbox_overlay_png
from lfm_vl_sft_dataset.ee_dynamic_world import fetch_dynamic_world_label, synthetic_label
from lfm_vl_sft_dataset.grid import build_reference_grid
from lfm_vl_sft_dataset.image_aug import iter_square_augmentations
from lfm_vl_sft_dataset.instances import (
    DYNAMIC_WORLD_CLASSES,
    class_focus_sentence,
    class_pixel_fractions,
    extract_regions,
    regions_to_normalized_json,
    rule_caption,
)
from lfm_vl_sft_dataset.jsonl_format import (
    caption_row,
    class_focus_caption_row,
    grounding_row,
    mapbox_overview_row,
    split_key,
)
from lfm_vl_sft_dataset.mapbox_still import fetch_mapbox_still_png
from lfm_vl_sft_dataset.s2_rgb import resolve_sentinel_item_dir, stack_s2_rgb_on_grid
from lfm_vl_sft_dataset.stac_meta import ee_filter_dates_from_iso, ee_filter_dates_from_query, fetch_item_datetime_iso
from lfm_vl_sft_dataset.tile_io import (
    TileSpec,
    clip_spatial_copy_to_tile,
    downsample_tile,
    iter_tiles,
    reflectance_stack_to_uint8,
    tile_valid_fraction,
)


@dataclass
class PipelineConfig:
    stac_url: str = "https://earth-search.aws.element84.com/v1"
    collection: str = "sentinel-2-l2a"
    native_tile: int = 512
    stride: int = 128
    output_size: int = 224
    min_area_px: int = 50
    max_per_class: int = 24
    min_valid_fraction: float = 0.35
    include_grounding: bool = True
    synthetic_labels: bool = False
    synthetic_seed: int = 0
    fetch_mapbox_still: bool = True
    mapbox_zoom: float = 12.0
    mapbox_size: int = 1280
    mapbox_retina: bool = True
    per_class_caption_rows: bool = True
    per_class_grounding_rows: bool = True
    min_class_fraction: float = 0.05
    max_classes_per_tile: int = 9
    # Optional extra PNG/JSONL views per tile: hflip + 90/180/270 (same mask semantics).
    image_aug: bool = False
    image_aug_hflip: bool = True
    image_aug_rot90: bool = True
    write_bbox_overlays: bool = False
    bbox_overlay_in_jsonl: bool = True
    bbox_overlay_line_width: int = 2


def _load_poi_json(poi_dir: Path) -> dict[str, Any]:
    p = poi_dir / "poi.json"
    if not p.is_file():
        raise FileNotFoundError(f"Missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _dataset_land_cover_label_meta(fetched: dict[str, Any]) -> dict[str, Any]:
    """
    Subset of EE label-fetch metadata safe to write under ``metadata/*.json`` without
    vendor or product names (no collection ids or internal keys like ``dw_*``).
    """
    public_keys = (
        "synthetic",
        "ee_image_count",
        "ee_image_count_padded",
        "download_url_host",
        "src_shape",
        "src_crs",
    )
    return {k: fetched[k] for k in public_keys if k in fetched}


def _overlay_tag_row(
    row: dict[str, Any],
    rgb_uint8: np.ndarray,
    boxes: list[tuple[str, tuple[int, int, int, int]]],
    *,
    stem: str,
    row_tag: str,
    overlay_idx: list[int],
    out_overlays: Path | None,
    cfg: PipelineConfig,
) -> dict[str, Any]:
    """Write ``overlays/{stem}__{idx}_{tag}.png`` and optionally add ``bbox_overlay_image`` to the row."""
    if not cfg.write_bbox_overlays or out_overlays is None:
        return row
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in row_tag)[:96]
    i = overlay_idx[0]
    overlay_idx[0] += 1
    fname = f"{stem}__{i:03d}_{safe}.png"
    out_path = out_overlays / fname
    write_bbox_overlay_png(
        rgb_uint8,
        boxes,
        out_path,
        line_width=cfg.bbox_overlay_line_width,
    )
    if cfg.bbox_overlay_in_jsonl:
        return {**row, "bbox_overlay_image": f"overlays/{fname}"}
    return row


def _emit_rows_for_rgb_mask(
    *,
    rgb_small: np.ndarray,
    mask_small: np.ndarray,
    stem: str,
    split: str,
    poi_id: str,
    ti: int,
    common_sidecar: dict[str, Any],
    out_images: Path,
    out_meta: Path,
    out_overlays: Path | None,
    cfg: PipelineConfig,
) -> list[tuple[str, dict[str, Any]]]:
    """Write one PNG + sidecar and return JSONL row tuples for that view."""
    rows: list[tuple[str, dict[str, Any]]] = []
    overlay_idx = [0]
    rel_img = f"images/{stem}.png"
    Image.fromarray(rgb_small).save(out_images / f"{stem}.png")

    min_px_ds = max(1, cfg.min_area_px * cfg.output_size // cfg.native_tile)
    regions = extract_regions(
        mask_small,
        min_area_px=min_px_ds,
        max_per_class=cfg.max_per_class,
    )
    cap = rule_caption(regions, image_w=cfg.output_size, image_h=cfg.output_size)
    fr = class_pixel_fractions(mask_small) if cfg.per_class_caption_rows else {}

    sidecar: dict[str, Any] = {
        **common_sidecar,
        "tile_index": ti,
        "tile_stem": stem,
        "caption": cap,
        "regions": [
            {
                "bbox": list(r.bbox_xyxy),
                "label": r.label,
                "class_id": r.class_id,
                "area_px": r.area_px,
            }
            for r in regions
        ],
    }
    if fr:
        sidecar["class_fractions"] = {str(k): round(v, 4) for k, v in fr.items()}
    (out_meta / f"{stem}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    all_boxes = [(r.label, r.bbox_xyxy) for r in regions]
    row0 = caption_row(rel_img, cap)
    rows.append((split, _overlay_tag_row(row0, rgb_small, all_boxes, stem=stem, row_tag="caption", overlay_idx=overlay_idx, out_overlays=out_overlays, cfg=cfg)))
    if cfg.include_grounding and regions:
        gj = regions_to_normalized_json(regions, image_w=cfg.output_size, image_h=cfg.output_size)
        row_g = grounding_row(
            rel_img,
            "land cover regions visible in this satellite imagery",
            gj,
        )
        rows.append(
            (
                split,
                _overlay_tag_row(
                    row_g,
                    rgb_small,
                    all_boxes,
                    stem=stem,
                    row_tag="ground_all",
                    overlay_idx=overlay_idx,
                    out_overlays=out_overlays,
                    cfg=cfg,
                ),
            )
        )

    if cfg.per_class_caption_rows and fr:
        ranked = sorted(fr.items(), key=lambda x: -x[1])[: cfg.max_classes_per_tile]
        for cid, frac in ranked:
            if frac < cfg.min_class_fraction:
                continue
            cname = DYNAMIC_WORLD_CLASSES[cid]
            ans = class_focus_sentence(cid, frac, regions=regions)
            cls_boxes = [(r.label, r.bbox_xyxy) for r in regions if r.class_id == cid]
            row_cf = class_focus_caption_row(rel_img, cname, ans)
            rows.append(
                (
                    split,
                    _overlay_tag_row(
                        row_cf,
                        rgb_small,
                        cls_boxes,
                        stem=stem,
                        row_tag=f"classfocus_{cname}",
                        overlay_idx=overlay_idx,
                        out_overlays=out_overlays,
                        cfg=cfg,
                    ),
                )
            )
            if cfg.include_grounding and cfg.per_class_grounding_rows:
                cls_regs = [r for r in regions if r.class_id == cid]
                if cls_regs:
                    gj_c = regions_to_normalized_json(
                        cls_regs, image_w=cfg.output_size, image_h=cfg.output_size
                    )
                    row_cg = grounding_row(rel_img, cname.replace("_", " "), gj_c)
                    cls_boxes2 = [(r.label, r.bbox_xyxy) for r in cls_regs]
                    rows.append(
                        (
                            split,
                            _overlay_tag_row(
                                row_cg,
                                rgb_small,
                                cls_boxes2,
                                stem=stem,
                                row_tag=f"ground_{cname}",
                                overlay_idx=overlay_idx,
                                out_overlays=out_overlays,
                                cfg=cfg,
                            ),
                        )
                    )

    return rows


def process_poi(
    poi_dir: Path,
    out_dir: Path,
    cfg: PipelineConfig,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Write PNG tiles + sidecar JSON under ``out_dir``; return ``(split, row_dict)`` for JSONL merge.
    """
    data = _load_poi_json(poi_dir)
    poi_id = str(data.get("poi_id") or poi_dir.name)
    west, south, east, north = (float(x) for x in data["bbox_wgs84"])
    lat = float(data["latitude"])
    lon = float(data["longitude"])
    stac_item_id = data.get("stac_item_id")
    split = split_key(poi_id)

    out_images = out_dir / "images"
    out_meta = out_dir / "metadata"
    out_overlays: Path | None = (out_dir / "overlays") if cfg.write_bbox_overlays else None
    out_images.mkdir(parents=True, exist_ok=True)
    out_meta.mkdir(parents=True, exist_ok=True)
    if out_overlays is not None:
        out_overlays.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, dict[str, Any]]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-build-lfm-vl-sft-dataset/1.0"})

    if cfg.fetch_mapbox_still:
        token = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
        if token:
            try:
                rel = fetch_mapbox_still_png(
                    lat=lat,
                    lon=lon,
                    poi_id=poi_id,
                    dest_dir=out_dir / "mapbox_stills",
                    session=session,
                    token=token,
                    zoom=cfg.mapbox_zoom,
                    size=cfg.mapbox_size,
                    retina=cfg.mapbox_retina,
                )
                meta = data.get("hf_row_meta") or {}
                country = meta.get("country_iso_alpha2") or ""
                addr = str(meta.get("address") or "")[:160]
                map_cap = (
                    f"Overhead context imagery (zoom {cfg.mapbox_zoom}) centered near "
                    f"{lat:.5f}°, {lon:.5f}°. Pairs with satellite imagery and land-cover outputs from the same area."
                )
                if country:
                    map_cap += f" ISO country: {country}."
                if addr:
                    map_cap += f" Vicinity: {addr}."
                mb_row = mapbox_overview_row(rel, map_cap)
                if cfg.write_bbox_overlays and out_overlays is not None:
                    mb_path = out_dir / rel
                    mb_rgb = np.asarray(Image.open(mb_path).convert("RGB"), dtype=np.uint8)
                    mb_idx = [0]
                    mb_row = _overlay_tag_row(
                        mb_row,
                        mb_rgb,
                        [],
                        stem=f"{poi_id}_mapbox",
                        row_tag="overview",
                        overlay_idx=mb_idx,
                        out_overlays=out_overlays,
                        cfg=cfg,
                    )
                rows.append((split, mb_row))
            except Exception as e:  # noqa: BLE001
                note = out_meta / f"{poi_id}_mapbox_error.txt"
                note.write_text(str(e), encoding="utf-8")

    grid = build_reference_grid(west, south, east, north, resolution_m=10.0, lat_anchor=lat, lon_anchor=lon)
    item_dir = resolve_sentinel_item_dir(poi_dir, str(stac_item_id) if stac_item_id else None)

    rgb, s2_meta = stack_s2_rgb_on_grid(
        item_dir,
        dst_crs=grid.crs,
        dst_transform=grid.transform,
        width=grid.width,
        height=grid.height,
    )

    item_iso = None
    if stac_item_id:
        item_iso = fetch_item_datetime_iso(
            stac_url=cfg.stac_url, collection=cfg.collection, item_id=str(stac_item_id)
        )
    if item_iso:
        d0, d1 = ee_filter_dates_from_iso(item_iso)
    else:
        d0, d1 = ee_filter_dates_from_query(str(data.get("datetime_query") or ""))

    if cfg.synthetic_labels:
        label = synthetic_label(grid.width, grid.height, seed=cfg.synthetic_seed + hash(poi_id) % 10_000)
        dw_meta: dict[str, Any] = {"synthetic": True}
    else:
        label, dw_meta = fetch_dynamic_world_label(
            west,
            south,
            east,
            north,
            date_start=d0,
            date_end=d1,
            dst_crs=grid.crs,
            dst_transform=grid.transform,
            width=grid.width,
            height=grid.height,
            datetime_query_fallback=str(data.get("datetime_query") or ""),
        )

    h, w = grid.height, grid.width
    t = cfg.native_tile
    if h < t or w < t:
        tile_specs: list[TileSpec] = [TileSpec(0, 0, h, w)]
    else:
        tile_specs = list(iter_tiles(h, w, t, cfg.stride))

    ti = 0
    for spec in tile_specs:
        r0, c0, th, tw = spec.row_off, spec.col_off, spec.height, spec.width
        if th < t or tw < t:
            rgb_pad = np.zeros((3, t, t), dtype=np.float32)
            lab_pad = np.full((t, t), 255, dtype=np.uint8)
            th_c, tw_c = clip_spatial_copy_to_tile(th, tw, t)
            rgb_pad[:, :th_c, :tw_c] = rgb[:, r0 : r0 + th_c, c0 : c0 + tw_c]
            lab_pad[:th_c, :tw_c] = label[r0 : r0 + th_c, c0 : c0 + tw_c]
            tile_rgb = rgb_pad
            tile_lab = lab_pad
        else:
            tile_rgb = rgb[:, r0 : r0 + th, c0 : c0 + tw]
            tile_lab = label[r0 : r0 + th, c0 : c0 + tw]

        vf = tile_valid_fraction(tile_lab, ignore=255)
        if vf < cfg.min_valid_fraction:
            continue

        rgb_hw3_u8 = reflectance_stack_to_uint8(tile_rgb)
        rgb_small, mask_small = downsample_tile(rgb_hw3_u8, tile_lab, output_size=cfg.output_size)

        stem = f"{poi_id}_t{ti:04d}"
        common_sidecar: dict[str, Any] = {
            "poi_id": poi_id,
            "split": split,
            "bbox_wgs84": [west, south, east, north],
            "latitude": lat,
            "longitude": lon,
            "stac_item_id": stac_item_id,
            "stac_rgb_meta": s2_meta,
            "land_cover_label_meta": _dataset_land_cover_label_meta(dw_meta),
            "grid": {
                "crs": grid.crs,
                "width": grid.width,
                "height": grid.height,
                "transform": list(grid.transform),
            },
            "native_tile": cfg.native_tile,
            "output_size": cfg.output_size,
            "tile_origin_native": [r0, c0],
        }

        rows.extend(
            _emit_rows_for_rgb_mask(
                rgb_small=rgb_small,
                mask_small=mask_small,
                stem=stem,
                split=split,
                poi_id=poi_id,
                ti=ti,
                common_sidecar=common_sidecar,
                out_images=out_images,
                out_meta=out_meta,
                out_overlays=out_overlays,
                cfg=cfg,
            )
        )

        if cfg.image_aug and (cfg.image_aug_hflip or cfg.image_aug_rot90):
            for suffix, rgb_a, mask_a in iter_square_augmentations(
                rgb_small,
                mask_small,
                hflip=cfg.image_aug_hflip,
                rot90=cfg.image_aug_rot90,
            ):
                if tile_valid_fraction(mask_a, ignore=255) < cfg.min_valid_fraction:
                    continue
                aug_sidecar = {**common_sidecar, "image_augmentation": suffix}
                rows.extend(
                    _emit_rows_for_rgb_mask(
                        rgb_small=rgb_a,
                        mask_small=mask_a,
                        stem=f"{stem}_{suffix}",
                        split=split,
                        poi_id=poi_id,
                        ti=ti,
                        common_sidecar=aug_sidecar,
                        out_images=out_images,
                        out_meta=out_meta,
                        out_overlays=out_overlays,
                        cfg=cfg,
                    )
                )

        ti += 1

    return rows


def discover_poi_dirs(poi_root: Path) -> list[Path]:
    return sorted([d for d in poi_root.iterdir() if d.is_dir() and d.name.startswith("poi_")])


def iter_base_poi_dirs(poi_root: Path) -> list[Path]:
    """
    Directories for **base** POIs only: ``poi_<digits>`` (any width), excluding ``poi_*_gNNN`` jitter folders.
    """
    out: list[Path] = []
    for d in poi_root.iterdir():
        if not d.is_dir() or not d.name.startswith("poi_"):
            continue
        if _GEO_JITTER_DIR.match(d.name):
            continue
        if re.fullmatch(r"poi_\d+", d.name):
            out.append(d)
    return sorted(out)


_GEO_JITTER_DIR = re.compile(r"^(poi_\d+)_g\d{3}$")


def base_poi_dir_name(poi_dir_name: str) -> str:
    """``poi_0000_g001`` → ``poi_0000``; plain ``poi_0001`` unchanged."""
    m = _GEO_JITTER_DIR.fullmatch(poi_dir_name)
    return m.group(1) if m else poi_dir_name


def filter_poi_dirs_max_base_pois(poi_dirs: list[Path], max_base: int) -> list[Path]:
    """
    Keep every folder whose **base** id is among the first ``max_base`` distinct bases
    in **sorted** ``poi_dirs`` order (so all ``poi_0000*`` variants stay when base ``poi_0000`` is included).
    """
    if max_base <= 0 or not poi_dirs:
        return poi_dirs
    bases_in_order: list[str] = []
    for d in poi_dirs:
        b = base_poi_dir_name(d.name)
        if b not in bases_in_order:
            bases_in_order.append(b)
    allowed = set(bases_in_order[:max_base])
    return [d for d in poi_dirs if base_poi_dir_name(d.name) in allowed]
