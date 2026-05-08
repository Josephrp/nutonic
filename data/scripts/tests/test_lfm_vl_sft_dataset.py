"""Offline tests for LFM-VL S2 + Dynamic World dataset helpers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from lfm_vl_sft_dataset.grid import build_reference_grid, utm_epsg
from lfm_vl_sft_dataset.instances import (
    DYNAMIC_WORLD_CLASSES,
    RegionAnn,
    class_focus_sentence,
    class_pixel_fractions,
    extract_regions,
    rule_caption,
)
from lfm_vl_sft_dataset.jsonl_format import (
    CAPTIONING_PROMPT,
    CLASS_FOCUS_USER_PROMPT,
    GROUNDING_PROMPT,
    MAPBOX_OVERVIEW_PROMPT,
    caption_row,
    split_key,
)
from lfm_vl_sft_dataset.bbox_overlay import write_bbox_overlay_png

from lfm_vl_sft_dataset.geo_jitter import sample_lat_lon_offset_m
from lfm_vl_sft_dataset.jsonl_format import append_jsonl_row, truncate_split_jsonl_files
from lfm_vl_sft_dataset.pipeline import (
    _dataset_land_cover_label_meta,
    base_poi_dir_name,
    filter_poi_dirs_max_base_pois,
    iter_base_poi_dirs,
)
from lfm_vl_sft_dataset.image_aug import iter_square_augmentations
from lfm_vl_sft_dataset.tile_io import (
    clip_spatial_copy_to_tile,
    downsample_tile,
    reflectance_stack_to_uint8,
)


def test_clip_spatial_copy_to_tile_avoids_pad_broadcast_error() -> None:
    """Regression: grid 511×513 with native_tile 512 must copy 511×512 into the pad."""
    t = 512
    th, tw = 511, 513
    th_c, tw_c = clip_spatial_copy_to_tile(th, tw, t)
    assert (th_c, tw_c) == (511, 512)
    r0, c0 = 0, 0
    rgb = np.linspace(0, 1, 3 * 511 * 513, dtype=np.float64).astype(np.float32).reshape(3, 511, 513)
    label = np.zeros((511, 513), dtype=np.uint8)
    rgb_pad = np.zeros((3, t, t), dtype=np.float32)
    lab_pad = np.full((t, t), 255, dtype=np.uint8)
    rgb_pad[:, :th_c, :tw_c] = rgb[:, r0 : r0 + th_c, c0 : c0 + tw_c]
    lab_pad[:th_c, :tw_c] = label[r0 : r0 + th_c, c0 : c0 + tw_c]
    assert rgb_pad.shape == (3, t, t) and np.any(rgb_pad != 0)
    assert lab_pad.shape == (t, t) and lab_pad[0, 0] == 0


def test_dataset_prompts_avoid_vendor_product_names() -> None:
    banned = ("mapbox", "sentinel", "dynamic world")
    for s in (CAPTIONING_PROMPT, MAPBOX_OVERVIEW_PROMPT, CLASS_FOCUS_USER_PROMPT, GROUNDING_PROMPT):
        low = s.lower()
        assert not any(b in low for b in banned)


def test_dataset_prompts_mention_satellite_imagery() -> None:
    for s in (CAPTIONING_PROMPT, CLASS_FOCUS_USER_PROMPT, GROUNDING_PROMPT):
        assert "satellite imagery" in s.lower()
    assert "satellite imagery" in MAPBOX_OVERVIEW_PROMPT.lower()


def test_dataset_prompts_exclude_dynamic_world_phrase() -> None:
    for s in (CAPTIONING_PROMPT, MAPBOX_OVERVIEW_PROMPT, CLASS_FOCUS_USER_PROMPT, GROUNDING_PROMPT):
        low = s.lower()
        assert "dynamic world" not in low
        assert "dynamicworld" not in low.replace(" ", "")


def test_land_cover_sidecar_meta_omits_vendor_collection_fields() -> None:
    raw = {
        "dw_collection": "GOOGLE/DYNAMICWORLD/V1",
        "ee_image_count": 2,
        "src_shape": (10, 11),
        "src_crs": "EPSG:32633",
    }
    pub = _dataset_land_cover_label_meta(raw)
    assert "dw_collection" not in pub
    blob = json.dumps(pub).lower()
    assert "dynamic" not in blob
    assert pub.get("ee_image_count") == 2


def test_utm_epsg_paris() -> None:
    assert utm_epsg(48.8566, 2.3522) == 32631


def test_reference_grid_shape() -> None:
    g = build_reference_grid(2.35, 48.85, 2.36, 48.86, resolution_m=10.0)
    assert g.width > 0 and g.height > 0
    assert g.crs.startswith("EPSG:326")


def test_reflectance_uint8() -> None:
    rgb = np.random.default_rng(0).random((3, 64, 64)).astype(np.float32) * 3000 + 500
    u8 = reflectance_stack_to_uint8(rgb)
    assert u8.shape == (64, 64, 3)
    assert u8.dtype == np.uint8


def test_write_bbox_overlay_png(tmp_path: Path) -> None:
    rgb = np.zeros((32, 32, 3), dtype=np.uint8)
    rgb[10:20, 5:25] = 200
    outp = tmp_path / "o.png"
    write_bbox_overlay_png(rgb, [("trees", (5, 10, 25, 20))], outp, line_width=2)
    assert outp.is_file() and outp.stat().st_size > 0


def test_iter_base_poi_dirs_excludes_jitter_and_six_digit(tmp_path: Path) -> None:
    root = tmp_path / "poi_root"
    root.mkdir()
    (root / "poi_000001").mkdir()
    (root / "poi_000001_g001").mkdir()
    (root / "poi_12").mkdir()
    (root / "other").mkdir()
    bases = [p.name for p in iter_base_poi_dirs(root)]
    assert bases == ["poi_000001", "poi_12"]


def test_filter_poi_dirs_max_base_pois() -> None:
    dirs = [
        Path("poi_0000"),
        Path("poi_0000_g001"),
        Path("poi_0000_g002"),
        Path("poi_0001"),
        Path("poi_0002_g001"),
    ]
    assert base_poi_dir_name("poi_0000_g001") == "poi_0000"
    assert base_poi_dir_name("poi_0001") == "poi_0001"
    f = filter_poi_dirs_max_base_pois(dirs, 2)
    assert f == [Path("poi_0000"), Path("poi_0000_g001"), Path("poi_0000_g002"), Path("poi_0001")]


def test_truncate_split_then_append_jsonl(tmp_path) -> None:
    d = tmp_path / "data"
    truncate_split_jsonl_files(d)
    assert (d / "train.jsonl").read_text() == ""
    append_jsonl_row(d / "train.jsonl", {"k": 1})
    append_jsonl_row(d / "train.jsonl", {"k": 2})
    lines = (d / "train.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_iter_square_augmentations_shapes() -> None:
    rgb = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
    mask = np.arange(9, dtype=np.uint8).reshape(3, 3)
    views = list(iter_square_augmentations(rgb, mask, hflip=True, rot90=True))
    assert len(views) == 4
    for _s, r, m in views:
        assert r.shape == (3, 3, 3) and m.shape == (3, 3)


def test_sample_lat_lon_offset_m() -> None:
    import random

    rng = random.Random(11)
    lat2, lon2, de, dn = sample_lat_lon_offset_m(45.0, 2.0, rng, 200.0)
    assert abs(lat2 - 45.0) < 0.01 and abs(lon2 - 2.0) < 0.01
    assert de**2 + dn**2 <= 200.0**2 + 1e-6


def test_downsample_aligns_mask() -> None:
    rng = np.random.default_rng(1)
    rgb = (rng.random((128, 128, 3)) * 255).astype(np.uint8)
    mask = rng.integers(0, 9, size=(128, 128), dtype=np.uint8)
    rs, ms = downsample_tile(rgb, mask, output_size=32)
    assert rs.shape == (32, 32, 3)
    assert ms.shape == (32, 32)


def test_extract_regions_and_caption() -> None:
    m = np.zeros((64, 64), dtype=np.uint8)
    m[10:30, 10:40] = 1  # trees
    m[40:55, 40:55] = 6  # built
    regs = extract_regions(m, min_area_px=50, max_per_class=8)
    assert regs
    cap = rule_caption(regs, image_w=64, image_h=64)
    assert "trees" in cap or "built" in cap
    assert "satellite imagery" in cap.lower()
    assert "sentinel" not in cap.lower()


def test_dynamic_world_class_coverage() -> None:
    assert len(DYNAMIC_WORLD_CLASSES) == 9


def test_caption_row_schema() -> None:
    row = caption_row("images/foo.png", "A satellite view.")
    assert row["messages"][0]["role"] == "user"
    assert any(c.get("type") == "image" for c in row["messages"][0]["content"])
    assert row["messages"][1]["role"] == "assistant"


def test_class_pixel_fractions() -> None:
    m = np.zeros((10, 10), dtype=np.uint8)
    m[:, :5] = 1
    m[:, 5:] = 2
    fr = class_pixel_fractions(m, ignore_value=255)
    assert abs(fr[1] - 0.5) < 0.01 and abs(fr[2] - 0.5) < 0.01


def test_class_focus_sentence() -> None:
    regs = [
        RegionAnn((0, 0, 2, 2), "trees", 1, 4),
        RegionAnn((5, 5, 7, 7), "trees", 1, 4),
    ]
    s = class_focus_sentence(1, 0.4, regions=regs)
    assert "trees" in s and "40" in s


def test_split_key_deterministic() -> None:
    assert split_key("poi_0000") in ("train", "validation", "test")
    a = split_key("poi_0000")
    b = split_key("poi_0000")
    assert a == b


def test_iter_dynamic_world_date_windows_order() -> None:
    from lfm_vl_sft_dataset.ee_dynamic_world import iter_dynamic_world_date_windows

    w = iter_dynamic_world_date_windows("2026-02-20", "2026-02-21", "")
    assert w[0] == ("2026-02-20", "2026-02-21", "scene_window")
    assert any(tag.startswith("symmetric_") for *_, tag in w)
    assert not any(tag == "stac_datetime_query_fallback" for *_, tag in w)


def test_iter_dynamic_world_date_windows_stac_fallback_last() -> None:
    from lfm_vl_sft_dataset.ee_dynamic_world import iter_dynamic_world_date_windows

    w = iter_dynamic_world_date_windows("2026-02-20", "2026-02-21", "2025-06-01/2025-08-01")
    assert w[-1][2] == "stac_datetime_query_fallback"
    assert w[-1][0] == "2025-06-01" and w[-1][1] == "2025-08-01"


def test_poi_dir_has_sentinel_l2a(tmp_path: Path) -> None:
    from lfm_vl_sft_dataset.s2_rgb import poi_dir_has_sentinel_l2a

    p = tmp_path / "poi_test"
    p.mkdir()
    assert not poi_dir_has_sentinel_l2a(p)
    s2 = p / "sentinel-2-l2a"
    s2.mkdir()
    assert not poi_dir_has_sentinel_l2a(p)
    (s2 / "S2_item_folder").mkdir()
    assert poi_dir_has_sentinel_l2a(p)


def test_hf_validate_repo_id() -> None:
    from lfm_vl_sft_dataset.hf_upload import _validate_repo_id

    _validate_repo_id("  NuTonic/some-repo  ")
    with pytest.raises(ValueError):
        _validate_repo_id("not_a_repo")


def test_resolve_hf_token_strips_outer_quotes() -> None:
    from lfm_vl_sft_dataset.hf_upload import _resolve_hf_token

    assert _resolve_hf_token('"mytoken"') == "mytoken"
    assert _resolve_hf_token("'x'") == "x"

