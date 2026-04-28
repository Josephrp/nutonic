"""Tests for TerraMind-conditioned VLM assessment SFT helpers and offline builder path."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lfm_vl_sft_dataset.terramind_assessment_sft import (
    assert_assistant_conservative,
    build_assessment_row,
    build_assessment_user_text,
    build_deterministic_assistant_text,
    cap_tim_context,
    decode_vlm_artifacts_to_files,
    lat_lon_from_materialize_bbox,
    load_seed_aois,
    merge_tim_into_context,
    remove_tim_coordinates_outside_manifest,
    split_for_sample,
    summarize_tim_context_for_training,
    tim_infer_config_from_materialize,
)


def test_summarize_tim_context_drops_tensor_like_keys() -> None:
    raw = {
        "tim_modality_outputs": {
            "LULC": {"internal_key": "k", "mean": 0.2, "tensor": [1, 2, 3], "x": [[1]]},
            "_inputs": {"should": "vanish"},
        },
        "engine": {"model_id": "m1", "patch_diagnostics": {"big": list(range(50))}},
    }
    slim = summarize_tim_context_for_training(raw)
    dumped = json.dumps(slim)
    assert "tensor" not in dumped
    assert "_inputs" not in dumped
    assert "m1" in dumped


def test_remove_tim_coordinates_when_outside_manifest_bbox() -> None:
    tim = {
        "tim_modality_outputs": {
            "Coordinates": {"latitude": 60.0, "longitude": -150.0, "confidence": 0.9},
        }
    }
    rm = {"bbox_wgs84": {"west": -118.4, "south": 34.0, "east": -118.2, "north": 34.1}}
    out = remove_tim_coordinates_outside_manifest(tim, rm)
    assert "Coordinates" not in out["tim_modality_outputs"]


def test_deterministic_assistant_skips_coords_outside_manifest() -> None:
    tim = {"tim_modality_outputs": {"Coordinates": {"latitude": 60.0, "longitude": -150.0}}}
    rm = {"bbox_wgs84": {"west": -118.4, "south": 34.0, "east": -118.2, "north": 34.1}}
    text = build_deterministic_assistant_text(
        analysis_profile="brief_only",
        tim_context=tim,
        canonical_surface_id="sentinel_fc",
        run_manifest_excerpt=rm,
    )
    assert "60.0000" not in text
    assert "approximate coordinate hint" not in text.lower()


def test_cap_tim_strips_secrets_and_truncates_samples() -> None:
    raw = {
        "tim_modality_outputs": {"X": {"inline_base64": "huge", "npz_base64": "nope", "sample": list(range(100))}},
    }
    capped = cap_tim_context(raw, max_sample_len=8)
    dumped = json.dumps(capped)
    assert "huge" not in dumped
    assert "nope" not in dumped
    assert capped["tim_modality_outputs"]["X"]["sample"] == list(range(8))


def test_merge_tim_prefers_modality_block() -> None:
    row = {"tim_modality_outputs": {"Coordinates": {"kind": "coordinates_wgs84", "latitude": 1.0, "longitude": 2.0}}}
    merged = merge_tim_into_context(row)
    assert "tim_modality_outputs" in merged


def test_decode_vlm_artifacts_writes_ordered_pngs(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "terramind_assessment_sft"
    mat = json.loads((fixture_dir / "materialize.json").read_text(encoding="utf-8"))
    img_root = tmp_path / "images"
    img_root.mkdir(parents=True, exist_ok=True)
    rels, canonical, roles = decode_vlm_artifacts_to_files(mat, img_root, stem="t0")
    assert len(rels) == 2
    assert roles == ["sentinel_fc", "cloud_mask_thumb"]
    assert rels[0].startswith("images/t0_sentinel_fc")
    assert rels[1].startswith("images/t0_cloud_mask_thumb")
    assert canonical == "sentinel_fc"
    assert (tmp_path / rels[0]).is_file()


def test_decode_includes_profile_overlay_png_after_contract_roles(tmp_path: Path) -> None:
    tiny = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lQVS+QAAAABJRU5ErkJggg=="
    mat = {
        "vlm_artifacts": [
            {
                "role": "sentinel_fc",
                "mime": "image/png",
                "width": 1,
                "height": 1,
                "inline_base64": tiny,
            },
            {
                "role": "firewatch_burn_change_heatmap",
                "mime": "image/png",
                "width": 4,
                "height": 4,
                "inline_base64": tiny,
            },
        ],
        "run_manifest": {},
    }
    img_root = tmp_path / "images"
    img_root.mkdir(parents=True, exist_ok=True)
    rels, _canonical, roles = decode_vlm_artifacts_to_files(mat, img_root, stem="x")
    assert roles == ["sentinel_fc", "firewatch_burn_change_heatmap"]
    assert len(rels) == 2


def test_lat_lon_from_materialize_bbox() -> None:
    mat = {"run_manifest": {"bbox_wgs84": {"west": -118.3, "south": 34.0, "east": -118.2, "north": 34.1}}}
    ll = lat_lon_from_materialize_bbox(mat)
    assert ll is not None
    lat, lon = ll
    assert abs(lat - 34.05) < 1e-6
    assert abs(lon - (-118.25)) < 1e-6


def test_tim_infer_config_stac_alignment() -> None:
    mat = {
        "run_manifest": {
            "stac": {"datetime": "2024-06-01T00:00:00Z", "item_id": "S2_ITEM_1"},
        },
    }
    seed = {
        "lat": 48.8566,
        "lon": 2.3522,
        "map_id": "m1",
        "location_id": "l1",
        "analysis_profile": "wildfire",
    }
    mr = {
        "bbox_half_km": 4.0,
        "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
        "stac_url": "https://earth-search.aws.element84.com/v1",
        "collection_id": "sentinel-2-l2a",
        "max_cloud_cover": 25.0,
        "datetime_interval": "2024-05-01/2024-05-31",
    }
    body = tim_infer_config_from_materialize(
        mat,
        seed,
        mr,
        model_id="terramind_v1_tiny_tim",
        device="cpu",
        tim_branch="S2L2A_full",
        rgb_jpeg_path=None,
    )
    assert body["config"]["modalities"] == ["S2L2A"]
    s2 = body["config"]["inputs"]["s2"]
    assert s2["scene_id"] == "S2_ITEM_1"
    assert s2["datetime"] == "2024-05-01/2024-05-31"


def test_tim_infer_config_rgb_mapbox_minimal_requires_jpeg() -> None:
    mat = {"run_manifest": {}}
    seed = {"lat": 1.0, "lon": 2.0, "map_id": "m", "location_id": "l", "analysis_profile": "brief_only"}
    mr = {"sentinel_fetch_mode": "MINIMAL_RGB"}
    with pytest.raises(ValueError, match="TIM_RGB_MAPBOX_MINIMAL_REQUIRES_JPEG"):
        tim_infer_config_from_materialize(
            mat,
            seed,
            mr,
            model_id="terramind_v1_tiny_tim",
            device="cpu",
            tim_branch="RGB_mapbox",
            rgb_jpeg_path=None,
        )


def test_user_text_lists_image_roles(tmp_path: Path) -> None:
    txt = build_assessment_user_text(
        analysis_profile="wildfire",
        canonical_surface_id="sentinel_fc",
        tim_context={"tim_modality_outputs": {}},
        run_manifest_excerpt=None,
        brief_fuse=None,
        tim_branch="S2L2A_full",
        image_roles=["sentinel_fc", "firewatch_burn_change_heatmap"],
    )
    assert "`sentinel_fc`" in txt
    assert "raw / sensor" in txt.lower()
    assert "firewatch_burn_change_heatmap" in txt
    assert "overlay" in txt.lower() or "diagnostic" in txt.lower()


def test_build_row_messages_multi_image() -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "terramind_assessment_sft"
    mat = json.loads((fixture_dir / "materialize.json").read_text(encoding="utf-8"))
    tim_line = json.loads((fixture_dir / "tim_export.jsonl").read_text(encoding="utf-8").splitlines()[0])
    tim_ctx = cap_tim_context(merge_tim_into_context(tim_line))
    row = build_assessment_row(
        sample_id="fixture_test_001",
        image_rel_paths=["images/a.png", "images/b.png"],
        analysis_profile="wildfire",
        canonical_surface_id="mapbox_rgb",
        tim_context=tim_ctx,
        run_manifest_excerpt={"scene_provenance": {"fixture": True}},
        brief_fuse=None,
        tim_branch="RGB_mapbox",
        source_mode="test",
    )
    user = row["messages"][1]["content"]
    img_parts = [c for c in user if c.get("type") == "image"]
    assert len(img_parts) == 2
    text_parts = [c for c in user if c.get("type") == "text"]
    assert text_parts
    low = text_parts[0]["text"].lower()
    assert "terramind" in low or "tim" in low
    assert "npz_base64" not in low


def test_deterministic_assistant_conservative() -> None:
    tim_ctx = {
        "tim_modality_outputs": {
            "Coordinates": {"kind": "coordinates_wgs84", "latitude": 10.0, "longitude": 20.0, "confidence": 0.5}
        }
    }
    text = build_deterministic_assistant_text(
        analysis_profile="oceanscout_ship_detection",
        tim_context=tim_ctx,
        canonical_surface_id="mapbox_rgb",
    )
    assert_assistant_conservative(text)
    assert "candidate" in text.lower() or "optical" in text.lower()


def test_split_for_sample_stable() -> None:
    a = split_for_sample("poi_0000")
    b = split_for_sample("poi_0000")
    assert a == b
    assert a in ("train", "validation", "test")


def test_load_seed_skips_comments(tmp_path: Path) -> None:
    p = tmp_path / "seeds.jsonl"
    p.write_text("# comment\n{\"lat\": 1.0, \"lon\": 2.0, \"analysis_profile\": \"brief_only\"}\n", encoding="utf-8")
    rows = load_seed_aois(p)
    assert len(rows) == 1
    assert rows[0]["lat"] == 1.0


def test_offline_cli_smoke(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "terramind_assessment_sft"
    out = tmp_path / "out_ds"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "build_terramind_assessment_sft.py"),
        "--offline-fixture",
        str(fx),
        "--out-dir",
        str(out),
        "--no-upload",
        "--max-samples",
        "1",
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    train = out / "data" / "train.jsonl"
    val = out / "data" / "validation.jsonl"
    test_f = out / "data" / "test.jsonl"
    assert train.is_file()
    all_lines: list[str] = []
    for p in (train, val, test_f):
        all_lines.extend([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])
    assert len(all_lines) >= 1
    line = all_lines[0]
    row = json.loads(line)
    assert row["messages"][0]["role"] == "system"


def test_replay_mat_json_and_tim_json_cli(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "terramind_assessment_sft"
    mat_path = tmp_path / "mat.json"
    mat_path.write_text((fx / "materialize.json").read_text(encoding="utf-8"), encoding="utf-8")
    tim_line = (fx / "tim_export.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (tmp_path / "tim.json").write_text(tim_line + "\n", encoding="utf-8")
    out = tmp_path / "out_ds"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "build_terramind_assessment_sft.py"),
        "--materialize-json",
        str(mat_path),
        "--tim-json",
        str(tmp_path / "tim.json"),
        "--out-dir",
        str(out),
        "--no-upload",
        "--max-samples",
        "1",
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any((out / "data" / name).is_file() for name in ("train.jsonl", "validation.jsonl", "test.jsonl"))
