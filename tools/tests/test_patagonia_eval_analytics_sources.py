"""Tests for the analytics-source axis (procedural / synthetic_oracle / TiM)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_analytics_sources import (  # noqa: E402
    build_procedural_analytics,
    fractions_from_dynamic_world_label,
    select_analytics,
    sentinel_fractions_from_scl,
)


class TestAnalyticsSources(unittest.TestCase):
    def test_scl_fractions_skip_clouds(self) -> None:
        scl = np.array([[6, 6, 4], [4, 8, 9]], dtype=np.uint8)  # 2 water, 2 vegetation, 2 clouds
        fr = sentinel_fractions_from_scl(scl)
        self.assertAlmostEqual(fr.get(0, 0.0), 0.5, places=5)  # water
        self.assertAlmostEqual(fr.get(1, 0.0), 0.5, places=5)  # trees (from veg)

    def test_dynamic_world_label_fractions(self) -> None:
        lbl = np.array([[0, 0, 1], [1, 8, 7]], dtype=np.uint8)
        fr = fractions_from_dynamic_world_label(lbl)
        self.assertAlmostEqual(sum(fr.values()), 1.0, places=5)
        self.assertAlmostEqual(fr.get(0, 0.0), 2 / 6, places=5)
        self.assertAlmostEqual(fr.get(1, 0.0), 2 / 6, places=5)

    def test_select_none_returns_none(self) -> None:
        out, src = select_analytics(
            "none",
            target_id="t1",
            profile="brief_only",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.6, 0: 0.4},
            scene_meta=None,
            tim_compact=None,
            tim_health=None,
        )
        self.assertIsNone(out)
        self.assertEqual(src, "none")

    def test_select_procedural_builds_compact(self) -> None:
        out, src = select_analytics(
            "procedural",
            target_id="t1",
            profile="land_use_change",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.6, 0: 0.4},
            scene_meta={"date": "2024-09-01"},
            tim_compact=None,
            tim_health=None,
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(src, "procedural")
        self.assertIn("tim_modality_outputs", out)
        self.assertIn("profile_analytics", out)
        self.assertEqual(out["profile_analytics"].get("source"), "procedural")

    def test_select_procedural_or_tim_falls_back_when_degenerate(self) -> None:
        out, src = select_analytics(
            "procedural_or_tim",
            target_id="t1",
            profile="land_use_change",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.6, 0: 0.4},
            scene_meta=None,
            tim_compact={"tim_modality_outputs": {}, "profile_analytics": {}},
            tim_health="degenerate",
        )
        self.assertIsNotNone(out)
        self.assertTrue(src.startswith("procedural_fallback_tim_health="))

    def test_select_procedural_or_tim_uses_tim_when_good(self) -> None:
        tim = {"tim_modality_outputs": {"LULC": {"class_fractions": {"trees": 0.6, "water": 0.4}}}, "profile_analytics": {"foo": "bar"}}
        out, src = select_analytics(
            "procedural_or_tim",
            target_id="t1",
            profile="land_use_change",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.6},
            scene_meta=None,
            tim_compact=tim,
            tim_health="good",
        )
        self.assertIs(out, tim)
        self.assertTrue(src.startswith("tim_generated"))

    def test_select_procedural_or_dw_prefers_dw(self) -> None:
        out, src = select_analytics(
            "procedural_or_dw",
            target_id="t1",
            profile="land_use_change",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.9},
            dynamic_world_fractions={0: 0.7, 1: 0.3},
            scene_meta=None,
            tim_compact=None,
            tim_health="degenerate",
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(src, "procedural_or_dw_dynamic_world")
        self.assertEqual(out["profile_analytics"].get("source"), "dynamic_world")

    def test_select_dynamic_world_fallback_scl(self) -> None:
        out, src = select_analytics(
            "dynamic_world",
            target_id="t1",
            profile="brief_only",
            target_lat=-50.0,
            target_lon=-72.0,
            sentinel_fractions={1: 0.5, 0: 0.5},
            dynamic_world_fractions=None,
            scene_meta=None,
            tim_compact=None,
            tim_health=None,
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(src, "dynamic_world_fallback_scl")
        self.assertEqual(out["profile_analytics"].get("source"), "procedural")

    def test_build_procedural_profile_source_override(self) -> None:
        out = build_procedural_analytics(
            target_id="t1",
            profile="land_use_change",
            sentinel_fractions={1: 1.0},
            profile_analytics_source="dynamic_world",
        )
        self.assertEqual(out["profile_analytics"].get("source"), "dynamic_world")


if __name__ == "__main__":
    unittest.main()
