"""Tests for EvalTarget.temporal_scenes wiring (resolution modes + TiM batch row + oracle coverage)."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from evaluate_vlm_patagonia import EvalTarget, default_patagonia_targets  # noqa: E402
from evaluate_vlm_patagonia_tim_e2e import (  # noqa: E402
    _temporal_datetime_for_target,
    _temporal_datetime_for_target_args,
    _temporal_scenes,
    _tim_batch_row_for_target,
)


def _mk_target(scenes: tuple[str, ...] = (), profile_hint: str = "") -> EvalTarget:
    return EvalTarget(
        target_id="t1",
        name="Test",
        lat=-50.0,
        lon=-72.0,
        zoom=10,
        category="andean_forest_lake",
        notes="",
        expected_any=(("water",),),
        analysis_profile_hint=profile_hint,
        temporal_scenes=scenes,
    )


class TestTemporalScenes(unittest.TestCase):
    def test_empty_scenes_returns_fallback(self) -> None:
        t = _mk_target(())
        self.assertEqual(_temporal_datetime_for_target(t, "2024-01-01/2024-12-31"), "2024-01-01/2024-12-31")

    def test_latest_picks_last_entry(self) -> None:
        t = _mk_target(("2024-01-01/2024-06-30", "2025-01-01/2025-06-30"))
        self.assertEqual(_temporal_datetime_for_target(t, "fallback", mode="latest"), "2025-01-01/2025-06-30")

    def test_union_combines_min_start_max_end(self) -> None:
        t = _mk_target(("2024-03-01/2024-06-30", "2025-01-01/2025-06-30"))
        self.assertEqual(_temporal_datetime_for_target(t, "fallback", mode="union"), "2024-03-01/2025-06-30")

    def test_union_single_scene_falls_back_to_latest(self) -> None:
        t = _mk_target(("2024-03-01/2024-06-30",))
        self.assertEqual(_temporal_datetime_for_target(t, "fallback", mode="union"), "2024-03-01/2024-06-30")

    def test_args_helper_honors_mode(self) -> None:
        t = _mk_target(("2024-03-01/2024-06-30", "2025-01-01/2025-06-30"))
        args = argparse.Namespace(temporal_scenes_mode="union")
        self.assertEqual(
            _temporal_datetime_for_target_args(args, t, default="fallback"),
            "2024-03-01/2025-06-30",
        )

    def test_normalized_scenes_strips_blanks(self) -> None:
        t = _mk_target(("  2024-03-01/2024-06-30  ", "", "  ", "2025-01-01/2025-06-30"))
        self.assertEqual(
            _temporal_scenes(t),
            ("2024-03-01/2024-06-30", "2025-01-01/2025-06-30"),
        )

    def test_tim_batch_row_uses_per_target_datetime_and_carries_scenes(self) -> None:
        t = _mk_target(("2024-01-01/2024-06-30", "2025-01-01/2025-06-30"), profile_hint="wildfire")
        args = argparse.Namespace(
            temporal_scenes_mode="latest",
            s2_datetime="2026-01-01/2026-04-30",
        )
        row = _tim_batch_row_for_target(args, t)
        self.assertEqual(row["datetime"], "2025-01-01/2025-06-30")
        self.assertEqual(row["temporal_scenes"], ["2024-01-01/2024-06-30", "2025-01-01/2025-06-30"])
        self.assertEqual(row["analysis_profile"], "wildfire")
        self.assertEqual(row["lat"], -50.0)
        self.assertEqual(row["lon"], -72.0)

    def test_tim_batch_row_falls_back_to_global_datetime(self) -> None:
        t = _mk_target(())
        args = argparse.Namespace(
            temporal_scenes_mode="latest",
            s2_datetime="2026-01-01/2026-04-30",
        )
        row = _tim_batch_row_for_target(args, t)
        self.assertEqual(row["datetime"], "2026-01-01/2026-04-30")
        self.assertNotIn("temporal_scenes", row)


class TestSyntheticOracleCoverage(unittest.TestCase):
    def test_default_targets_have_oracle_entries(self) -> None:
        oracle_path = REPO / "tools" / "data" / "patagonia_synthetic_oracle.yaml"
        raw = yaml.safe_load(oracle_path.read_text(encoding="utf-8")) or {}
        self.assertIsInstance(raw, dict)
        valid_classes = {
            "water",
            "trees",
            "grass",
            "flooded_vegetation",
            "crops",
            "shrub_and_scrub",
            "built",
            "bare_ground",
            "snow_and_ice",
        }
        ids = [t.target_id for t in default_patagonia_targets()]
        missing = [tid for tid in ids if tid not in raw]
        self.assertEqual(missing, [], f"Missing oracle entries for: {missing}")
        for tid, entry in raw.items():
            self.assertIn("sentinel_fractions", entry, f"{tid} has no sentinel_fractions")
            fr = entry["sentinel_fractions"]
            self.assertIsInstance(fr, dict)
            self.assertGreater(len(fr), 0, f"{tid} has empty fractions")
            for cls, val in fr.items():
                self.assertIn(cls, valid_classes, f"{tid} has unknown class {cls}")
                self.assertGreaterEqual(float(val), 0.0)
                self.assertLessEqual(float(val), 1.0)

    def test_temporal_scene_targets_have_pairs(self) -> None:
        ids_with_scenes = {t.target_id: _temporal_scenes(t) for t in default_patagonia_targets() if _temporal_scenes(t)}
        self.assertIn("pat_chubut_steppe_wildfire_context", ids_with_scenes)
        self.assertIn("pat_golfo_san_matias_marsh", ids_with_scenes)
        for tid, scenes in ids_with_scenes.items():
            self.assertGreaterEqual(len(scenes), 1, f"{tid} has empty temporal_scenes")
            for rng in scenes:
                self.assertIn("/", rng, f"{tid} entry {rng!r} is not a STAC datetime range")


if __name__ == "__main__":
    unittest.main()
