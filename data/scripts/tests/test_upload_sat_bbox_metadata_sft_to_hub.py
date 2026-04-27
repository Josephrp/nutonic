"""Tests for upload_sat_bbox_metadata_sft_to_hub staging decision logic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]


def _import_helpers():
    sys.path.insert(0, str(_SCRIPTS))
    from upload_sat_bbox_metadata_sft_to_hub import hub_sharding_recommended  # noqa: E402

    return hub_sharding_recommended


def test_hub_sharding_recommended_false_when_dirs_small(tmp_path: Path) -> None:
    hub_sharding_recommended = _import_helpers()
    root = tmp_path / "ds"
    (root / "data").mkdir(parents=True)
    (root / "images").mkdir()
    (root / "analysis_images").mkdir()
    assert not hub_sharding_recommended(root, max_flat_files=8000)


def test_hub_sharding_recommended_true_when_sft_metadata_rows_exceeds(tmp_path: Path) -> None:
    hub_sharding_recommended = _import_helpers()
    root = tmp_path / "ds"
    (root / "data").mkdir(parents=True)
    (root / "images").mkdir()
    sm = root / "metadata" / "sft_metadata_rows"
    sm.mkdir(parents=True)
    for i in range(8001):
        (sm / f"row_{i}.json").write_text("{}", encoding="utf-8")
    assert hub_sharding_recommended(root, max_flat_files=8000)


def test_hub_sharding_recommended_true_when_analysis_images_flat_exceeds(tmp_path: Path) -> None:
    hub_sharding_recommended = _import_helpers()
    root = tmp_path / "ds"
    (root / "data").mkdir(parents=True)
    (root / "images").mkdir()
    ad = root / "analysis_images"
    ad.mkdir()
    for i in range(3):
        (ad / f"a{i}.png").write_bytes(b"x")
    assert not hub_sharding_recommended(root, max_flat_files=8000)
    for i in range(3, 8002):
        (ad / f"a{i}.png").write_bytes(b"x")
    assert hub_sharding_recommended(root, max_flat_files=8000)


def test_shard_script_rewrites_analysis_image_path_in_jsonl(tmp_path: Path) -> None:
    """End-to-end: shard_lfm_vl_dataset_for_hub remaps analysis_images/* in JSONL."""
    src = tmp_path / "src"
    dst = tmp_path / "dst_hub"
    (src / "data").mkdir(parents=True)
    row = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": "images/x0.png"},
                    {"type": "image", "image": "analysis_images/y0.png"},
                ],
            }
        ]
    }
    (src / "images").mkdir()
    (src / "images" / "x0.png").write_bytes(b"i0")
    (src / "images" / "x1.png").write_bytes(b"i1")
    (src / "analysis_images").mkdir()
    (src / "analysis_images" / "y0.png").write_bytes(b"a0")
    (src / "analysis_images" / "y1.png").write_bytes(b"a1")
    (src / "data" / "train.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    shard = _SCRIPTS / "shard_lfm_vl_dataset_for_hub.py"
    subprocess.run(
        [
            sys.executable,
            str(shard),
            "--src",
            str(src),
            "--dst",
            str(dst),
            "--max-files-per-dir",
            "1",
            "--link",
            "none",
        ],
        check=True,
    )
    out_line = (dst / "data" / "train.jsonl").read_text(encoding="utf-8").strip()
    out = json.loads(out_line)
    imgs = [p["image"] for p in out["messages"][0]["content"] if p.get("type") == "image"]
    assert imgs[0].startswith("images/s00000/")
    assert imgs[1].startswith("analysis_images/s00000/")


def test_shard_script_shards_metadata_sft_metadata_rows(tmp_path: Path) -> None:
    """metadata/sft_metadata_rows/*.json must shard (Hub 10k dir limit)."""
    src = tmp_path / "src"
    dst = tmp_path / "dst_hub"
    (src / "data").mkdir(parents=True)
    (src / "data" / "train.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    sm = src / "metadata" / "sft_metadata_rows"
    sm.mkdir(parents=True)
    for i in range(5):
        (sm / f"side_{i}.json").write_text(json.dumps({"i": i, "p": "images/a.png"}), encoding="utf-8")

    shard = _SCRIPTS / "shard_lfm_vl_dataset_for_hub.py"
    subprocess.run(
        [
            sys.executable,
            str(shard),
            "--src",
            str(src),
            "--dst",
            str(dst),
            "--max-files-per-dir",
            "2",
            "--link",
            "none",
        ],
        check=True,
    )
    shard_dirs = [p.name for p in (dst / "metadata" / "sft_metadata_rows").iterdir() if p.is_dir()]
    assert "s00000" in shard_dirs
    assert "s00001" in shard_dirs
    assert (dst / "metadata" / "sft_metadata_rows" / "s00000" / "side_0.json").is_file()
    assert (dst / "metadata" / "sft_metadata_rows" / "s00002" / "side_4.json").is_file()
