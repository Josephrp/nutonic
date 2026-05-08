"""Tests for ``useful_hints_coverage.json`` emission (no Hub)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HFJ = Path(__file__).resolve().parents[1]
if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

from entrypoint_hf_hydration import _write_useful_hints_coverage_report


def test_useful_hints_coverage_present_and_absent(tmp_path: Path) -> None:
    hints = tmp_path / "useful_hints"
    hints.mkdir(parents=True)
    (hints / "poi_0000.json").write_text("{}", encoding="utf-8")
    cache = tmp_path / "cache_seg"
    (cache / "reports").mkdir(parents=True, exist_ok=True)

    _write_useful_hints_coverage_report(
        cache_cv=cache,
        location_ids=["poi_0000", "poi_0001"],
        hints_dir=hints,
        content_version="cvtest",
        skip_geo_hints=False,
    )
    raw = json.loads((cache / "reports" / "useful_hints_coverage.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == "nutonic.useful_hints_coverage.v1"
    by_id = {r["location_id"]: r for r in raw["locations"]}
    assert by_id["poi_0000"]["useful_hints_status"] == "present"
    assert by_id["poi_0001"]["useful_hints_status"] == "absent"
    assert "reason" in by_id["poi_0001"]


def test_useful_hints_coverage_skipped_geo(tmp_path: Path) -> None:
    hints = tmp_path / "uh2"
    hints.mkdir()
    cache = tmp_path / "cv2"
    (cache / "reports").mkdir(parents=True, exist_ok=True)
    _write_useful_hints_coverage_report(
        cache_cv=cache,
        location_ids=["poi_x"],
        hints_dir=hints,
        content_version="cv2",
        skip_geo_hints=True,
    )
    raw = json.loads((cache / "reports" / "useful_hints_coverage.json").read_text(encoding="utf-8"))
    assert raw["locations"][0]["useful_hints_status"] == "skipped_geo_hints"
