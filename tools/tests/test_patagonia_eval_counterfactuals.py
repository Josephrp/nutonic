"""Tests for counterfactual probes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_counterfactuals import (  # noqa: E402
    caption_disagreement,
    caption_responsiveness,
    perturb_half_redact,
    perturb_tim_payload_flip,
    perturb_wrong_analytics,
)


def _rich_analytics() -> dict:
    return {
        "tim_modality_outputs": {
            "LULC": {"class_fractions": {"trees": 0.6, "water": 0.3, "snow_and_ice": 0.1}},
            "NDVI": {"sample": [0.5, 0.6, 0.45]},
        },
        "profile_analytics": {
            "profile": "land_use_change",
            "land_transition": {
                "top_transitions": [
                    {"from": "trees", "to": "bare_ground", "count": 8, "pct": 5.0},
                ],
                "class_distribution": [
                    {"label": "trees", "fraction": 0.6},
                    {"label": "water", "fraction": 0.3},
                ],
            },
        },
    }


class TestCounterfactuals(unittest.TestCase):
    def test_wrong_analytics_changes_json(self) -> None:
        original = _rich_analytics()
        out, diag = perturb_wrong_analytics(original, profile="land_use_change")
        self.assertTrue(diag.get("json_changed"))
        self.assertNotEqual(out, original)
        # Class fractions reversed: smallest now has largest value.
        cf = out["tim_modality_outputs"]["LULC"]["class_fractions"]
        self.assertGreater(cf["snow_and_ice"], cf["trees"])

    def test_wrong_analytics_marine_plants_or_clears_vessels(self) -> None:
        original = {
            "tim_modality_outputs": {"LULC": {"class_fractions": {"water": 1.0}}},
            "profile_analytics": {"vessel_candidates": []},
        }
        out, diag = perturb_wrong_analytics(original, profile="oceanscout_ship_detection")
        assert out is not None
        vc = out["profile_analytics"]["vessel_candidates"]
        self.assertEqual(len(vc), 1)
        self.assertEqual(diag.get("vessel_candidates_planted"), 1)

    def test_half_redact_clears_body(self) -> None:
        original = _rich_analytics()
        out, diag = perturb_half_redact(original)
        self.assertTrue(diag["json_changed"])
        assert out is not None
        pa = out["profile_analytics"]
        self.assertTrue(pa["redacted"])
        self.assertNotIn("land_transition", pa)

    def test_tim_payload_flip_negates_samples(self) -> None:
        original = _rich_analytics()
        out, _ = perturb_tim_payload_flip(original)
        assert out is not None
        ndvi = out["tim_modality_outputs"]["NDVI"]["sample"]
        self.assertEqual(ndvi[0], -0.5)

    def test_responsiveness_zero_when_identical(self) -> None:
        s, _ = caption_responsiveness("hello world", "hello world")
        self.assertEqual(s, 0.0)

    def test_responsiveness_high_when_different(self) -> None:
        s, _ = caption_responsiveness(
            "Forest dominates with water in the south",
            "Snow-covered ridgelines and bare-rock terrain",
        )
        self.assertGreater(s, 0.5)

    def test_caption_disagreement_prefers_true(self) -> None:
        # Truth: trees=60%, water=30%; planted: trees=10%, water=60%.
        # Caption asserts forest ~60% (close to true) and water ~30% (close to true).
        cap = "The chip shows forest at about 60% of the area with water around 30%."
        s, d = caption_disagreement(
            cap,
            true_class_pcts={"trees": 60.0, "water": 30.0},
            wrong_class_pcts={"trees": 10.0, "water": 60.0},
        )
        self.assertGreaterEqual(s, 0.5)
        self.assertEqual(d["n_percent_claims"], 2)


if __name__ == "__main__":
    unittest.main()
