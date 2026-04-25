"""Shared helpers for PRO profile dataset builder scripts."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image
from pystac_client import Client

from lfm_vl_sft_dataset.change_instances import ChangeRegion, regions_to_normalized_json
from lfm_vl_sft_dataset.grid import build_reference_grid
from lfm_vl_sft_dataset.jsonl_format import make_multi_image_vlm_message, split_key
from lfm_vl_sft_dataset.temporal_stac import TemporalScene, download_item_assets, search_temporal_pair
from lfm_vl_sft_dataset.tile_io import (
    TileSpec,
    clip_spatial_copy_to_tile,
    downsample_tile,
    iter_tiles,
    reflectance_stack_to_uint8,
)

S2_OPTIONAL_ASSETS = frozenset(["product_metadata"])
S2_MINIMAL_ALLOWLIST = frozenset(
    [
        "blue",
        "green",
        "red",
        "nir",
        "nir08",
        "swir16",
        "swir22",
        "scl",
        "visual",
        "thumbnail",
        "tileinfo_metadata",
        "granule_metadata",
    ]
)

@dataclass(frozen=True)
class TemporalPairFetchConfig:
    stac_url: str
    collection: str
    bbox_half_km: float
    pre_window_days: int
    post_window_days: int
    max_cloud_pct: float
    sentinel_mode: str = "minimal"
    skip_existing: bool = True
    required_assets: list[str] | None = None


@dataclass(frozen=True)
class TemporalPairResult:
    event_id: str
    pre_scene: TemporalScene
    post_scene: TemporalScene
    pre_item_dir: Path
    post_item_dir: Path


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def _resolve_item(client: Client, *, collection: str, item_id: str) -> Any:
    items = list(client.search(collections=[collection], ids=[item_id], max_items=1).items())
    if not items:
        raise RuntimeError(f"STAC item not found: {item_id}")
    return items[0]


def _download_item_assets(
    *,
    item: Any,
    item_dir: Path,
    sentinel_mode: str,
    required_assets: list[str] | None,
    skip_existing: bool,
    session: requests.Session,
) -> tuple[list[str], list[str]]:
    allowlist: set[str] | None = None
    if sentinel_mode == "minimal":
        allowlist = set(required_assets) if required_assets else set(S2_MINIMAL_ALLOWLIST)
    return _download_item_assets_with_allowlist(
        item=item,
        item_dir=item_dir,
        allowlist=allowlist,
        skip_existing=skip_existing,
        session=session,
    )


def _download_item_assets_with_allowlist(
    *,
    item: Any,
    item_dir: Path,
    allowlist: set[str] | None,
    skip_existing: bool,
    session: requests.Session,
) -> tuple[list[str], list[str]]:
    _path, errs, warns = download_item_assets(
        item=item,
        item_root=item_dir.parent,
        session=session,
        asset_allowlist=allowlist,
        optional_asset_keys=set(S2_OPTIONAL_ASSETS),
        skip_existing=skip_existing,
        timeout_s=45,
    )
    return errs, warns


def fetch_temporal_pair_for_event(
    *,
    event_id: str,
    lat: float,
    lon: float,
    event_date: str,
    work_root: Path,
    cfg: TemporalPairFetchConfig,
    session: requests.Session,
) -> TemporalPairResult | None:
    """Search and materialize pre/post STAC scenes for one event."""
    pre_scene, post_scene = search_temporal_pair(
        stac_url=cfg.stac_url,
        collection=cfg.collection,
        lat=lat,
        lon=lon,
        bbox_half_km=cfg.bbox_half_km,
        event_date=event_date,
        pre_window_days=cfg.pre_window_days,
        post_window_days=cfg.post_window_days,
        max_cloud_pct=cfg.max_cloud_pct,
    )
    if pre_scene is None or post_scene is None:
        print(
            f"[{event_id}] temporal pair: STAC search returned pre={pre_scene is not None} "
            f"post={post_scene is not None} (check network to {cfg.stac_url}, "
            f"``--max-cloud-pct``, date windows, or try ``--sentinel-mode minimal``).",
            file=sys.stderr,
        )
        return None

    client = Client.open(cfg.stac_url)
    pre_item = _resolve_item(client, collection=cfg.collection, item_id=pre_scene.item_id)
    post_item = _resolve_item(client, collection=cfg.collection, item_id=post_scene.item_id)

    event_dir = work_root / _safe_name(event_id) / cfg.collection
    pre_dir = event_dir / _safe_name(pre_scene.item_id)
    post_dir = event_dir / _safe_name(post_scene.item_id)
    pre_dir.mkdir(parents=True, exist_ok=True)
    post_dir.mkdir(parents=True, exist_ok=True)

    pre_errs, _ = _download_item_assets(
        item=pre_item,
        item_dir=pre_dir,
        sentinel_mode=cfg.sentinel_mode,
        required_assets=cfg.required_assets,
        skip_existing=cfg.skip_existing,
        session=session,
    )
    post_errs, _ = _download_item_assets(
        item=post_item,
        item_dir=post_dir,
        sentinel_mode=cfg.sentinel_mode,
        required_assets=cfg.required_assets,
        skip_existing=cfg.skip_existing,
        session=session,
    )
    if pre_errs or post_errs:
        print(
            f"[{event_id}] temporal pair: STAC matched scenes but asset download failed "
            f"(sentinel_mode={cfg.sentinel_mode!r}). pre_errors={pre_errs[:5]!r} "
            f"post_errors={post_errs[:5]!r}. "
            "Try ``--sentinel-mode minimal`` (lean allowlist), clear partial files under work-dir, "
            "or fix outbound HTTPS to COG hosts.",
            file=sys.stderr,
        )
        return None

    return TemporalPairResult(
        event_id=event_id,
        pre_scene=pre_scene,
        post_scene=post_scene,
        pre_item_dir=pre_dir,
        post_item_dir=post_dir,
    )


def build_tile_specs(height: int, width: int, native_tile: int, stride: int) -> list[TileSpec]:
    if height < native_tile or width < native_tile:
        return [TileSpec(0, 0, height, width)]
    return list(iter_tiles(height, width, native_tile, stride))


def crop_or_pad_tile(
    array: np.ndarray,
    *,
    row_off: int,
    col_off: int,
    height: int,
    width: int,
    native_tile: int,
    fill_value: float | int = 0,
) -> np.ndarray:
    """
    Crop a tile from `array` and pad to native_tile if needed.

    Supports:
      - (C, H, W) arrays
      - (H, W) arrays
    """
    if array.ndim == 3:
        c, _, _ = array.shape
        out = np.full((c, native_tile, native_tile), fill_value, dtype=array.dtype)
        th_c, tw_c = clip_spatial_copy_to_tile(height, width, native_tile)
        out[:, :th_c, :tw_c] = array[:, row_off : row_off + th_c, col_off : col_off + tw_c]
        return out
    if array.ndim == 2:
        out2 = np.full((native_tile, native_tile), fill_value, dtype=array.dtype)
        th_c, tw_c = clip_spatial_copy_to_tile(height, width, native_tile)
        out2[:th_c, :tw_c] = array[row_off : row_off + th_c, col_off : col_off + tw_c]
        return out2
    raise ValueError(f"Unsupported array shape for crop_or_pad_tile: {array.shape}")


def save_pair_images(
    *,
    out_dir: Path,
    stem: str,
    rgb_pre_hw3: np.ndarray,
    rgb_post_hw3: np.ndarray,
) -> tuple[str, str]:
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    rel_pre = f"images/{stem}_t0.png"
    rel_post = f"images/{stem}_t1.png"
    Image.fromarray(rgb_pre_hw3).save(out_dir / rel_pre)
    Image.fromarray(rgb_post_hw3).save(out_dir / rel_post)
    return rel_pre, rel_post


def write_metadata(out_dir: Path, stem: str, obj: dict[str, Any]) -> None:
    md = out_dir / "metadata"
    md.mkdir(parents=True, exist_ok=True)
    (md / f"{stem}.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")


def make_pair_rows(
    *,
    split_id: str,
    image_paths: list[str],
    system_text: str,
    caption_prompt: str,
    caption_text: str,
    grounding_prompt: str,
    regions: list[ChangeRegion],
    image_size: int,
    metadata: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    rows.append(
        (
            split_id,
            make_multi_image_vlm_message(
                image_paths,
                caption_prompt,
                caption_text,
                system_text=system_text,
                metadata=metadata,
            ),
        )
    )
    if regions:
        regions_json = regions_to_normalized_json(regions, image_w=image_size, image_h=image_size)
        rows.append(
            (
                split_id,
                make_multi_image_vlm_message(
                    image_paths,
                    grounding_prompt,
                    regions_json,
                    system_text=system_text,
                    regions=[
                        {"label": r.label, "bbox": list(r.bbox_xyxy), "area_px": r.area_px}
                        for r in regions
                    ],
                    metadata=metadata,
                ),
            )
        )
    return rows


def split_for_event(event_id: str) -> str:
    return split_key(event_id)


def downsample_rgb_and_mask(
    rgb_stack_chw: np.ndarray,
    mask_hw: np.ndarray,
    *,
    output_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    rgb_u8 = reflectance_stack_to_uint8(rgb_stack_chw)
    return downsample_tile(rgb_u8, mask_hw, output_size=output_size)

