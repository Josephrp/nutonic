"""Tests for assemble_manifest.py and assemble_ranked_clue_pack.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assemble_manifest import assemble_manifest, main as assemble_main
from assemble_ranked_clue_pack import build_ranked_pack, main as ranked_main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "assemble_manifest"


def test_assemble_manifest_fixture_full_and_public() -> None:
    catalog = FIXTURE / "catalog"
    still_index = FIXTURE / "still_index.json"
    hints = FIXTURE / "useful_hints"
    ai = FIXTURE / "ai_guesses.json"
    policy = Path(__file__).resolve().parents[1] / "tier_policy.default.yaml"

    repo_root = Path(__file__).resolve().parents[3]
    full_doc, pub_doc = assemble_manifest(
        catalog_root=catalog,
        repo_root=repo_root,
        still_index_path=still_index,
        useful_hints_dir=hints,
        ai_guesses_path=ai,
        tier_policy_path=policy,
        output_dir=catalog,
        content_version=None,
        engine_version="0.9.0-test",
        expose_public_round_truth=False,
        skip_catalog_lint=False,
        skip_hint_validate=False,
    )

    assert full_doc["content_version"] == "nutonic.assemble.fixture.v1"
    assert full_doc["engine_version"] == "0.9.0-test"
    assert len(full_doc["maps"]) == 2
    assert len(full_doc["locations"]) == 2
    assert len(full_doc["ai_guesses"]) == 2

    loc_a = next(x for x in full_doc["locations"] if x["location_id"] == "asm_fix_a")
    assert loc_a["truth_lat"] == 10.0
    assert loc_a["still_bundle_id"] == "nutonic.still.v1.asm_fix_a"
    assert loc_a["useful_hints"]["tier_1"].startswith("Tropical")

    assert pub_doc["locations"] == []
    assert pub_doc["ai_guesses"] == []

    ranked = build_ranked_pack(
        full_doc,
        {"asm_fix_a": True, "asm_fix_b": False},
    )
    assert ranked["schema_version"] == "nutonic.ranked_clue_pack.v1"
    assert len(ranked["clues"]) == 1
    assert ranked["clues"][0]["map_id"] == "asm_fix_a"
    assert "truth_lat" not in json.dumps(ranked)
    assert len(ranked["ai_guesses"]) == 1
    assert ranked["ai_guesses"][0]["map_id"] == "asm_fix_a"


def test_assemble_manifest_cli_writes_files(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    catalog = FIXTURE / "catalog"
    code = assemble_main(
        [
            "--catalog-root",
            str(catalog),
            "--repo-root",
            str(repo),
            "--still-index",
            str(FIXTURE / "still_index.json"),
            "--useful-hints-dir",
            str(FIXTURE / "useful_hints"),
            "--ai-guesses",
            str(FIXTURE / "ai_guesses.json"),
            "--output-dir",
            str(tmp_path),
            "--engine-version",
            "cli-test",
        ]
    )
    assert code == 0
    full_path = tmp_path / "manifest.full.json"
    pub_path = tmp_path / "manifest.public.json"
    assert full_path.is_file()
    assert pub_path.is_file()
    full = json.loads(full_path.read_text(encoding="utf-8"))
    assert full["engine_version"] == "cli-test"


def test_assemble_ranked_cli_writes_pack(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    catalog = FIXTURE / "catalog"
    out_m = tmp_path / "m"
    out_m.mkdir()
    assert (
        assemble_main(
            [
                "--catalog-root",
                str(catalog),
                "--repo-root",
                str(repo),
                "--still-index",
                str(FIXTURE / "still_index.json"),
                "--useful-hints-dir",
                str(FIXTURE / "useful_hints"),
                "--ai-guesses",
                str(FIXTURE / "ai_guesses.json"),
                "--output-dir",
                str(out_m),
            ]
        )
        == 0
    )
    out_r = tmp_path / "r"
    out_r.mkdir()
    code = ranked_main(
        [
            "--manifest",
            str(out_m / "manifest.full.json"),
            "--catalog-root",
            str(catalog),
            "--output-dir",
            str(out_r),
        ]
    )
    assert code == 0
    assert (out_r / "ranked_clue_pack.json").is_file()
    assert (out_r / "ranked_clues" / "asm_fix_a.json").is_file()
