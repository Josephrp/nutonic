"""Tests for metadata-first sat-bbox procedural SFT builder."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lfm_vl_sft_dataset.instances import RegionAnn, regions_to_normalized_json
from lfm_vl_sft_dataset.sat_bbox_metadata_sft import (
    PROCEDURAL_OCEANSCOUT_SHORELINE_POLICY,
    SatBBoxMetadataSftConfig,
    build_analysis_image_spec,
    build_procedural_profile_analytics,
    build_procedural_tim_context,
    collect_split_leakage_bases,
    normalize_production_analysis_profile,
    passes_bloat_filters,
    procedural_tim_fractions,
    render_analysis_image,
    run_metadata_sft_build,
    tim_context_for_user_prompt,
    validate_normalized_grounding_json,
)


def test_validate_normalized_grounding_json_accepts_rounded_boxes() -> None:
    regs = [
        RegionAnn(bbox_xyxy=(10, 10, 100, 120), label="trees", class_id=1, area_px=100),
    ]
    js = regions_to_normalized_json(regs, image_w=224, image_h=224)
    ok, _reason = validate_normalized_grounding_json(js)
    assert ok


def test_bloat_filter_rejects_inputs_substring() -> None:
    ok, reason = passes_bloat_filters("normal text then _inputs leak")
    assert not ok
    assert "bloat" in reason


def test_normalize_production_analysis_profile_vessel_monitoring_alias() -> None:
    assert normalize_production_analysis_profile("vessel_monitoring") == "oceanscout_ship_detection"
    assert normalize_production_analysis_profile(" oceanscout_ship_detection ") == "oceanscout_ship_detection"


def test_build_procedural_oceanscout_analytics_includes_shoreline_policy() -> None:
    sentinel = {0: 0.1, 1: 0.5, 2: 0.1, 6: 0.3}
    tim = procedural_tim_fractions(sentinel, profile="oceanscout_ship_detection")
    sample = [1.0] * 32
    inputs_meta = {"s2_stac": {"stac_item_id": "x", "stac_datetime": None, "eo_cloud_cover": 0.0}}
    pa = build_procedural_profile_analytics(
        profile="oceanscout_ship_detection",
        sentinel_fractions=sentinel,
        tim_fractions=tim,
        sample=sample,
        inputs_meta=inputs_meta,
    )
    assert pa["shoreline_policy"] == PROCEDURAL_OCEANSCOUT_SHORELINE_POLICY


def test_vessel_monitoring_alias_emits_oceanscout_profile_row() -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini"
    cfg = SatBBoxMetadataSftConfig(
        dataset_root=fx,
        split_filter="all",
        max_rows=1,
        task_mix=frozenset({"production_analysis"}),
        analysis_profiles=("vessel_monitoring",),
        require_local_images=True,
    )
    rows, stats = run_metadata_sft_build(cfg)
    assert len(rows) == 1
    assert rows[0][2]["analysis_profile"] == "oceanscout_ship_detection"
    assert stats.by_task["production_analysis"] == 1


def test_run_build_on_fixture_emits_caption_and_grounding(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini"
    cfg = SatBBoxMetadataSftConfig(
        dataset_root=fx,
        split_filter="all",
        max_rows=20,
        task_mix=frozenset({"caption", "grounding"}),
        require_local_images=True,
    )
    rows, stats = run_metadata_sft_build(cfg)
    assert rows
    assert stats.emitted >= 2
    texts = [json.dumps(r[1], ensure_ascii=False) for r in rows]
    joined = "\n".join(texts)
    assert "dominated by trees" in joined
    assert "trees" in joined and "built" in joined


def test_tim_context_for_user_prompt_strips_sentinel_echoes() -> None:
    meta = {
        "stac_item_id": "S2_fixture",
        "stac_datetime": None,
        "eo_cloud_cover": 12.5,
        "latitude": 1.0,
        "longitude": 2.0,
    }
    sentinel_fr = {1: 0.5, 6: 0.3, 2: 0.2}
    tim_fr = procedural_tim_fractions(sentinel_fr, profile="brief_only")
    full = build_procedural_tim_context(
        meta=meta, sentinel_fractions=sentinel_fr, profile="brief_only", tim_fractions=tim_fr
    )
    red = tim_context_for_user_prompt(full)
    blob = json.dumps(red, ensure_ascii=False)
    assert "inputs_meta" not in red
    assert "scene_provenance" not in (red.get("profile_analytics") or {})
    assert "dominant_sentinel_classes" not in blob
    assert "S2_fixture" not in blob


def test_production_analysis_rows_use_profile_specific_summary() -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini"
    cfg = SatBBoxMetadataSftConfig(
        dataset_root=fx,
        split_filter="all",
        max_rows=5,
        task_mix=frozenset({"production_analysis"}),
        require_local_images=True,
    )
    rows, stats = run_metadata_sft_build(cfg)
    assert stats.by_task["production_analysis"] == 5
    assert stats.mapbox_paired == 5
    profiles = [side["analysis_profile"] for _split, _row, side in rows]
    assert profiles == [
        "brief_only",
        "land_use_change",
        "wildfire",
        "flood_pulse",
        "oceanscout_ship_detection",
    ]
    by_profile = {side["analysis_profile"]: row for _split, row, side in rows}
    first_images = [
        part["image"]
        for part in rows[0][1]["messages"][1]["content"]
        if isinstance(part, dict) and part.get("type") == "image"
    ]
    assert len(first_images) == 3
    assert first_images[0] == "images/s00000/poi_000099_g001_t0000.png"
    assert first_images[1] == "mapbox_stills/s00000/poi_000099.png"
    assert first_images[2].startswith("analysis_images/")
    assert first_images[2].endswith("__analysis_brief_only.png")
    land_text = by_profile["land_use_change"]["messages"][2]["content"][0]["text"]
    assert "built area is predicted to increase" in land_text
    assert "trees is" not in land_text
    flood_text = by_profile["flood_pulse"]["messages"][2]["content"][0]["text"]
    assert "water extent is predicted to increase" in flood_text
    user0 = next(
        p["text"]
        for p in rows[0][1]["messages"][1]["content"]
        if isinstance(p, dict) and p.get("type") == "text"
    )
    assert "sentinel_2_sidecar" not in user0
    assert "metadata-derived" not in user0.lower()
    assert "This satellite imagery is dominated" not in user0
    assert rows[0][2].get("sentinel_sidecar", {}).get("source") == "sentinel_2_sidecar"


def test_render_analysis_image_writes_png(tmp_path: Path) -> None:
    fr = {0: 0.05, 1: 0.4, 2: 0.1, 6: 0.2}
    tim_fr = procedural_tim_fractions(fr, profile="land_use_change")
    regs = [
        RegionAnn(bbox_xyxy=(10, 10, 80, 90), label="trees", class_id=1, area_px=100),
    ]
    spec = build_analysis_image_spec(
        profile="land_use_change",
        tile_stem="poi_fixture_t0000",
        sentinel_fractions=fr,
        tim_fractions=tim_fr,
        regions=regs,
    )
    dest = tmp_path / "analysis.png"
    render_analysis_image(spec, dest)
    assert dest.is_file() and dest.stat().st_size > 200


def test_split_leakage_drops_rows(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    (root / "data").mkdir(parents=True)
    (root / "metadata" / "s0").mkdir(parents=True)
    tiny_png = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "scripts"
        / "tests"
        / "fixtures"
        / "sat_bbox_sft_mini"
        / "images"
        / "s00000"
        / "poi_000099_g001_t0000.png"
    ).read_bytes()
    (root / "images" / "s0").mkdir(parents=True)
    (root / "images" / "s0" / "poi_000001_g001_t0000.png").write_bytes(tiny_png)
    (root / "images" / "s0" / "poi_000001_g002_t0000.png").write_bytes(tiny_png)
    (root / "data" / "train.jsonl").write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": "images/s0/poi_000001_g001_t0000.png"},
                            {"type": "text", "text": "x"},
                        ],
                    }
                ]
            }
        )
        + "\n"
        + json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": "images/s0/poi_000001_g002_t0000.png"},
                            {"type": "text", "text": "x"},
                        ],
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    meta_a = {
        "poi_id": "poi_000001_g001",
        "tile_stem": "poi_000001_g001_t0000",
        "split": "train",
        "output_size": 224,
        "caption": "Cap a.",
        "regions": [{"bbox": [0, 0, 50, 50], "label": "trees", "class_id": 1, "area_px": 100}],
        "class_fractions": {"1": 0.9},
    }
    meta_b = {
        "poi_id": "poi_000001_g002",
        "tile_stem": "poi_000001_g002_t0000",
        "split": "validation",
        "output_size": 224,
        "caption": "Cap b.",
        "regions": [{"bbox": [0, 0, 50, 50], "label": "trees", "class_id": 1, "area_px": 100}],
        "class_fractions": {"1": 0.9},
    }
    (root / "metadata" / "s0" / "poi_000001_g001_t0000.json").write_text(
        json.dumps(meta_a, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (root / "metadata" / "s0" / "poi_000001_g002_t0000.json").write_text(
        json.dumps(meta_b, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    leaked = collect_split_leakage_bases(
        [root / "metadata" / "s0" / "poi_000001_g001_t0000.json", root / "metadata" / "s0" / "poi_000001_g002_t0000.json"]
    )
    assert "poi_000001" in leaked
    cfg = SatBBoxMetadataSftConfig(dataset_root=root, task_mix=frozenset({"caption"}), require_local_images=True)
    rows, stats = run_metadata_sft_build(cfg)
    assert rows == []
    assert stats.dropped["split_leakage"] >= 1


def test_cli_smoke_on_fixture(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini"
    out = tmp_path / "out"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "build_sat_bbox_metadata_sft.py"),
        "--dataset-root",
        str(fx),
        "--out-dir",
        str(out),
        "--max-rows",
        "5",
        "--task-mix",
        "caption",
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    summary = json.loads(r.stdout.strip())
    assert summary["rows_emitted"] >= 1

