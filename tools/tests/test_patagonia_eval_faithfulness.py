"""Tests for the deterministic faithfulness scorer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_faithfulness import faithfulness_score  # noqa: E402


def _empty_lulc_analytics(profile: str) -> dict:
    return {
        "tim_modality_outputs": {"LULC": {"class_fractions": {}}},
        "profile_analytics": {"profile": profile, "land_transition": {"transition_matrix": [], "top_transitions": []}},
    }


def _rich_lulc_analytics() -> dict:
    return {
        "tim_modality_outputs": {
            "LULC": {
                "class_fractions": {"trees": 0.55, "water": 0.30, "snow_and_ice": 0.10, "bare_ground": 0.05}
            }
        },
        "profile_analytics": {
            "profile": "land_use_change",
            "land_transition": {
                "transition_matrix": [{"from": "trees", "to": "trees", "count": 12, "pct": 55.0}],
                "top_transitions": [
                    {"from": "trees", "to": "bare_ground", "count": 8, "pct": 5.0, "delta": -0.05},
                ],
                "class_distribution": [
                    {"class_id": 1, "label": "trees", "fraction": 0.55},
                    {"class_id": 0, "label": "water", "fraction": 0.30},
                    {"class_id": 8, "label": "snow_and_ice", "fraction": 0.10},
                ],
            },
        },
    }


class TestFaithfulness(unittest.TestCase):
    def test_no_analytics_returns_none(self) -> None:
        s, d = faithfulness_score("any caption", None, profile="brief_only")
        self.assertIsNone(s)
        self.assertEqual(d.get("reason"), "no_analytics_in_prompt")

    def test_empty_body_with_hedge_scores_modest(self) -> None:
        cap = "Optical-only Sentinel-2 chip; cannot infer specific land-use transitions from the provided analytics."
        s, _ = faithfulness_score(cap, _empty_lulc_analytics("land_use_change"), profile="land_use_change")
        self.assertIsNotNone(s)
        assert s is not None
        self.assertGreaterEqual(s, 0.55)
        self.assertLess(s, 0.85)

    def test_empty_body_without_hedge_is_penalized(self) -> None:
        cap = "Land-use change identified: 70% cropland and 20% built area."
        s, d = faithfulness_score(cap, _empty_lulc_analytics("land_use_change"), profile="land_use_change")
        assert s is not None
        self.assertLessEqual(s, 0.40)
        self.assertIn("no_hedge_when_body_sparse", d.get("penalties", []))

    def test_rich_body_supported_claims_score_high(self) -> None:
        cap = (
            "Sentinel-2 imagery shows dominant forest (~55%) over the chip with a large lake to the west "
            "(~30%) and snow-capped ridgelines (~10%). Confidence is moderate; optical-only chip."
        )
        s, d = faithfulness_score(cap, _rich_lulc_analytics(), profile="land_use_change")
        assert s is not None
        self.assertGreaterEqual(s, 0.75)
        self.assertIn("trees", d.get("supported_class_claims", []))

    def test_fabricated_class_claim_is_penalized(self) -> None:
        cap = "Caption asserts dominant cropland and built infrastructure across the tile."
        s, d = faithfulness_score(cap, _rich_lulc_analytics(), profile="land_use_change")
        assert s is not None
        self.assertLess(s, 0.6)
        self.assertTrue(d.get("fabricated_class_claims"))

    def test_anti_narration_caps_score(self) -> None:
        cap = (
            "Sentinel-2 imagery shows dominant forest (~55%) and water (~30%).\n[captions: optical only]\n"
            "Confidence moderate."
        )
        s, d = faithfulness_score(cap, _rich_lulc_analytics(), profile="land_use_change")
        assert s is not None
        self.assertLessEqual(s, 0.40)
        self.assertIn("captions_marker", d.get("anti_narration_hits", []))

    def test_marine_denying_vessel_candidates_is_penalized(self) -> None:
        analytics = {
            "tim_modality_outputs": {"LULC": {"class_fractions": {"water": 1.0}}},
            "profile_analytics": {
                "profile": "oceanscout_ship_detection",
                "vessel_candidates": [{"candidate_id": "x", "score": 0.8}],
                "detection_score_summary": {"sample_count": 32},
            },
        }
        cap = "Open-water tile; no ships visible. Confidence is high."
        s, d = faithfulness_score(cap, analytics, profile="oceanscout_ship_detection")
        assert s is not None
        self.assertLess(s, 0.55)
        self.assertIn("denies_vessel_candidates_present", d.get("penalties", []))

    def test_numeric_wide_miss_penalty(self) -> None:
        cap = (
            "Sentinel-2 imagery shows water (~30%) and forest. The dominant class appears to be 90% cropland, "
            "with confidence moderate."
        )
        s, d = faithfulness_score(cap, _rich_lulc_analytics(), profile="land_use_change")
        assert s is not None
        self.assertGreater(d.get("numeric_wide_misses", 0), 0)


if __name__ == "__main__":
    unittest.main()
