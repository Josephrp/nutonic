"""Tests for ``hydration_cache_finalize`` (no torch / no Hub)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HFJ = Path(__file__).resolve().parents[1]
if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

from hydration_cache_finalize import finalize_hydration_cache_post_streetview


def _write_still_index(path: Path, lids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "locations": [
                    {
                        "location_id": lid,
                        "map_id": lid,
                        "center_lat": 0.0,
                        "center_lon": 0.0,
                    }
                    for lid in lids
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_finalize_drops_failed_poi(tmp_path: Path) -> None:
    cv = tmp_path / "cvseg"
    cat = tmp_path / "catalog" / "locations"
    cat.mkdir(parents=True, exist_ok=True)
    (cv / "streetview").mkdir(parents=True, exist_ok=True)
    (cv / "reports").mkdir(parents=True, exist_ok=True)
    (cv / "geo_context").mkdir(parents=True, exist_ok=True)
    (cv / "useful_hints").mkdir(parents=True, exist_ok=True)
    stills = cv / "build_stills" / "stills"
    stills.mkdir(parents=True, exist_ok=True)

    _write_still_index(cv / "build_stills" / "still_index.json", ["poi_0000", "poi_0001"])
    (cv / "streetview" / "poi_0000.json").write_text("{}", encoding="utf-8")
    (cv / "streetview" / "poi_0001.json").write_text("{}", encoding="utf-8")
    (cv / "geo_context" / "poi_0000.json").write_text("{}", encoding="utf-8")
    (cv / "geo_context" / "poi_0001.json").write_text("{}", encoding="utf-8")
    (cv / "useful_hints" / "poi_0000.json").write_text("{}", encoding="utf-8")
    (cv / "useful_hints" / "poi_0001.json").write_text("{}", encoding="utf-8")
    (stills / "poi_0000.jpg").write_bytes(b"x")
    (stills / "poi_0000.meta.json").write_text("{}", encoding="utf-8")
    (stills / "poi_0001.jpg").write_bytes(b"x")
    (stills / "poi_0001.meta.json").write_text("{}", encoding="utf-8")
    (cat / "poi_0000.yaml").write_text(
        "location_id: poi_0000\nmap_id: poi_0000\ntruth_lat: -1.0\ntruth_lon: 2.0\n",
        encoding="utf-8",
    )
    (cat / "poi_0001.yaml").write_text(
        "location_id: poi_0001\nmap_id: poi_0001\ntruth_lat: 3.0\ntruth_lon: -4.0\n",
        encoding="utf-8",
    )

    (cv / "reports" / "streetview_failures.json").write_text(
        json.dumps([{"location_id": "poi_0001", "error": "503", "type": "HTTPError"}]),
        encoding="utf-8",
    )

    included = finalize_hydration_cache_post_streetview(
        cache_cv=cv,
        catalog_locations_dir=cat,
        content_version="testcv",
    )
    assert included == ["poi_0000"]
    assert (cv / "streetview" / "poi_0000.json").is_file()
    assert not (cv / "streetview" / "poi_0001.json").exists()
    assert not (cv / "geo_context" / "poi_0001.json").exists()
    assert not (cat / "poi_0001.yaml").exists()
    idx = json.loads((cv / "build_stills" / "still_index.json").read_text(encoding="utf-8"))
    assert [x["location_id"] for x in idx["locations"]] == ["poi_0000"]
    man = json.loads((cv / "reports" / "hydration_included_location_ids.json").read_text(encoding="utf-8"))
    assert man["location_ids"] == ["poi_0000"]
    assert len(man["excluded"]) == 1
    assert json.loads((cv / "reports" / "streetview_failures.json").read_text(encoding="utf-8")) == []
    seed = json.loads((cv / "reports" / "tim_batch_seed.json").read_text(encoding="utf-8"))
    assert seed["schema_version"] == "nutonic.tim_batch_seed.v1"
    assert len(seed["rows"]) == 1
    assert seed["rows"][0]["location_id"] == "poi_0000"
    assert seed["rows"][0]["truth_lat"] == -1.0
    assert seed["rows"][0]["truth_lon"] == 2.0


def test_finalize_drops_missing_streetview_json(tmp_path: Path) -> None:
    cv = tmp_path / "cv2"
    cat = tmp_path / "cat2" / "locations"
    cat.mkdir(parents=True, exist_ok=True)
    (cv / "streetview").mkdir(parents=True, exist_ok=True)
    (cv / "reports").mkdir(parents=True, exist_ok=True)
    (cv / "build_stills" / "stills").mkdir(parents=True, exist_ok=True)
    _write_still_index(cv / "build_stills" / "still_index.json", ["poi_x"])
    (cv / "reports" / "streetview_failures.json").write_text("[]\n", encoding="utf-8")
    (cat / "poi_x.yaml").write_text("x: 1\n", encoding="utf-8")

    included = finalize_hydration_cache_post_streetview(
        cache_cv=cv,
        catalog_locations_dir=cat,
        content_version="cv",
    )
    assert included == []
