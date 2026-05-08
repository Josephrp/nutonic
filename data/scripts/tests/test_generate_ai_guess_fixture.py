"""Tests for generate_ai_guess_fixture.py (TiM Coordinates + interim modes)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from generate_ai_guess_fixture import (
    extract_tim_coordinates,
    generate,
    load_tim_jsonl,
    main as gen_main,
)
from geo_nutonic import destination_point_km, haversine_km

CATALOG = Path(__file__).resolve().parent / "fixtures" / "assemble_manifest" / "catalog"
TIM_JSONL = Path(__file__).resolve().parent / "fixtures" / "tim_export" / "sample_tim.jsonl"


def test_destination_point_round_trip_distance() -> None:
    lon0, lat0 = 16.3738, 48.2082
    dist_km = 50.0
    bearing = 127.0
    lon1, lat1 = destination_point_km(lon0, lat0, bearing, dist_km)
    got = haversine_km(lon0, lat0, lon1, lat1)
    assert abs(got - dist_km) < 0.2


def test_extract_tim_coordinates_top_level_and_nested() -> None:
    top = {"ai_lat": 1.0, "ai_lon": 2.0, "location_id": "x", "map_id": "m"}
    assert extract_tim_coordinates(top) == (1.0, 2.0)

    nested = {
        "tim_modality_outputs": {
            "Coordinates": {"kind": "coordinates_wgs84", "latitude": -33.8, "longitude": 151.2}
        }
    }
    assert extract_tim_coordinates(nested) == (-33.8, 151.2)

    shorthand = {"tim_modality_outputs": {"Coordinates": {"lat": 10.0, "lon": 20.0}}}
    assert extract_tim_coordinates(shorthand) == (10.0, 20.0)


def test_load_tim_jsonl_fixture() -> None:
    m = load_tim_jsonl(TIM_JSONL)
    assert m[("asm_fix_a", "asm_fix_a")] == (11.5, 21.25)
    assert m[("asm_fix_b", "asm_fix_b")] == (-4.0, 128.5)


def test_mode_terramind_tim_jsonl_writes(tmp_path: Path) -> None:
    out = tmp_path / "ai_guesses.json"
    rows = generate(
        catalog_root=CATALOG,
        mode="terramind_tim_jsonl",
        output_path=out,
        tim_export=TIM_JSONL,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=None,
        bearing_deg=None,
        csv_path=None,
        seed=None,
        min_km=None,
        max_km=None,
        min_sep_km=1.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    assert len(rows) == 2
    by_id = {r["location_id"]: r for r in rows}
    assert by_id["asm_fix_a"]["ai_lat"] == 11.5
    assert by_id["asm_fix_a"]["ai_lon"] == 21.25


def test_decoy_offset_separation(tmp_path: Path) -> None:
    out = tmp_path / "ai.json"
    generate(
        catalog_root=CATALOG,
        mode="decoy_offset",
        output_path=out,
        tim_export=None,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=80.0,
        bearing_deg=45.0,
        csv_path=None,
        seed=None,
        min_km=None,
        max_km=None,
        min_sep_km=1.0,
        min_ai_vs_truth_km=5.0,
        max_ai_vs_truth_km=None,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    for row in data["ai_guesses"]:
        loc = next(
            x
            for x in [
                {"truth_lat": 10.0, "truth_lon": 20.0, "location_id": "asm_fix_a"},
                {"truth_lat": -5.5, "truth_lon": 130.0, "location_id": "asm_fix_b"},
            ]
            if x["location_id"] == row["location_id"]
        )
        d = haversine_km(loc["truth_lon"], loc["truth_lat"], row["ai_lon"], row["ai_lat"])
        assert d >= 5.0 - 1e-3
        assert abs(d - 80.0) < 0.25


def test_fixed_table_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "ai.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["location_id", "map_id", "ai_lat", "ai_lon"])
        w.writeheader()
        w.writerow(
            {"location_id": "asm_fix_a", "map_id": "asm_fix_a", "ai_lat": "1.0", "ai_lon": "2.0"}
        )
        w.writerow(
            {
                "location_id": "asm_fix_b",
                "map_id": "asm_fix_b",
                "ai_lat": "-10.0",
                "ai_lon": "100.0",
            }
        )
    out = tmp_path / "out.json"
    generate(
        catalog_root=CATALOG,
        mode="fixed_table",
        output_path=out,
        tim_export=None,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=None,
        bearing_deg=None,
        csv_path=csv_path,
        seed=None,
        min_km=None,
        max_km=None,
        min_sep_km=1.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    ids = {r["location_id"]: r for r in data["ai_guesses"]}
    assert ids["asm_fix_a"]["ai_lat"] == 1.0


def test_tim_overlay_prefer_tim_true(tmp_path: Path) -> None:
    out = tmp_path / "merged.json"
    generate(
        catalog_root=CATALOG,
        mode="decoy_offset",
        output_path=out,
        tim_export=TIM_JSONL,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=100.0,
        bearing_deg=0.0,
        csv_path=None,
        seed=None,
        min_km=None,
        max_km=None,
        min_sep_km=1.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    ids = {r["location_id"]: r for r in data["ai_guesses"]}
    assert ids["asm_fix_a"]["ai_lat"] == 11.5


def test_tim_overlay_prefer_tim_false_conflict(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    with pytest.raises(ValueError, match="Conflicting AI coordinates"):
        generate(
            catalog_root=CATALOG,
            mode="decoy_offset",
            output_path=out,
            tim_export=TIM_JSONL,
            tim_dir=None,
            prefer_tim=False,
            tim_match_tol_km=1e-9,
            delta_km=100.0,
            bearing_deg=0.0,
            csv_path=None,
            seed=None,
            min_km=None,
            max_km=None,
            min_sep_km=1.0,
            min_ai_vs_truth_km=0.0,
            max_ai_vs_truth_km=None,
        )


def test_cli_exit_conflict_code(tmp_path: Path) -> None:
    p = tmp_path / "ai.json"
    code = gen_main(
        [
            "--catalog-root",
            str(CATALOG),
            "--mode",
            "decoy_offset",
            "--tim-export",
            str(TIM_JSONL),
            "--no-prefer-tim",
            "--tim-match-tol-km",
            "0",
            "--delta-km",
            "100",
            "--bearing-deg",
            "0",
            "--output",
            str(p),
        ]
    )
    assert code == 13


def test_random_seeded_deterministic(tmp_path: Path) -> None:
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    generate(
        catalog_root=CATALOG,
        mode="random_seeded",
        output_path=out1,
        tim_export=None,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=None,
        bearing_deg=None,
        csv_path=None,
        seed=123,
        min_km=50.0,
        max_km=200.0,
        min_sep_km=10.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    generate(
        catalog_root=CATALOG,
        mode="random_seeded",
        output_path=out2,
        tim_export=None,
        tim_dir=None,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=None,
        bearing_deg=None,
        csv_path=None,
        seed=123,
        min_km=50.0,
        max_km=200.0,
        min_sep_km=10.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_terramind_tim_dir(tmp_path: Path) -> None:
    d = tmp_path / "timdir"
    d.mkdir()
    for lid, mid, lat, lon in [
        ("asm_fix_a", "asm_fix_a", 11.5, 21.25),
        ("asm_fix_b", "asm_fix_b", -4.0, 128.5),
    ]:
        payload = {
            "location_id": lid,
            "map_id": mid,
            "tim_modality_outputs": {
                "Coordinates": {"kind": "coordinates_wgs84", "latitude": lat, "longitude": lon}
            },
        }
        (d / f"{lid}.json").write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "ai.json"
    generate(
        catalog_root=CATALOG,
        mode="terramind_tim_dir",
        output_path=out,
        tim_export=None,
        tim_dir=d,
        prefer_tim=True,
        tim_match_tol_km=0.05,
        delta_km=None,
        bearing_deg=None,
        csv_path=None,
        seed=None,
        min_km=None,
        max_km=None,
        min_sep_km=1.0,
        min_ai_vs_truth_km=0.0,
        max_ai_vs_truth_km=None,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["ai_guesses"]) == 2
