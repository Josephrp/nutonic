"""Tests for TiM–caption alignment heuristic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_scoring import SCORE_WEIGHT_PRESETS, ScoreWeights, score_patagonia_multimodal  # noqa: E402
from patagonia_eval_tim_alignment import score_tim_alignment  # noqa: E402
from evaluate_vlm_patagonia import default_patagonia_targets  # noqa: E402


class TestTimAlignment(unittest.TestCase):
    def test_none_compact(self) -> None:
        s, d = score_tim_alignment("Some caption.", None, analysis_profile="brief_only")
        self.assertIsNone(s)
        self.assertEqual(d.get("reason"), "no_tim_compact")

    def test_oceanscout_engagement(self) -> None:
        compact = {
            "tim_modality_outputs": {"LULC": {"sample": [0.1, 0.9]}},
            "profile_analytics": {
                "profile": "oceanscout_ship_detection",
                "vessel_candidates": [{"candidate_id": "sample-0001", "score": 0.8}],
            },
        }
        cap = (
            "Dominant open ocean in the Sentinel-2 chip. TiM JSON suggests vessel candidates as model-shaped signals; "
            "optical view cannot verify hulls. Limitations: cloud and pseudo-SAR ambiguity."
        )
        s, d = score_tim_alignment(cap, compact, analysis_profile="oceanscout_ship_detection")
        self.assertIsNotNone(s)
        assert s is not None
        self.assertGreaterEqual(s, 0.7)
        self.assertTrue(d.get("mentions_tim_bridge") or d.get("hits_theme"))

    def test_multimodal_includes_tim_alignment_block(self) -> None:
        target = default_patagonia_targets()[0]
        compact = {
            "tim_modality_outputs": {"NDVI": {"sample": [0.2, 0.4]}},
            "profile_analytics": {"profile": "land_use_change", "land_transition": {"top_transitions": []}},
        }
        cap = (
            "Mixed forest and lake visible. The TiM analytics JSON hints at land-cover dynamics; "
            "optical chip alone is approximate. Confidence is moderate."
        )
        out = score_patagonia_multimodal(
            cap,
            target,
            threshold=0.4,
            gold_boxes=None,
            weights=ScoreWeights(0.2, 0.0, 0.3, 0.5),
            score_mode="composite",
            pass_metric="composite",
            tim_compact=compact,
            analysis_profile="land_use_change",
        )
        self.assertIn("tim_alignment", out)
        self.assertIsNotNone(out["tim_alignment"]["score"])
        self.assertGreater(float(out["tim_alignment"]["score"]), 0.4)

    def test_presets_sum_weights(self) -> None:
        for name, w in SCORE_WEIGHT_PRESETS.items():
            total = w.lexical + w.grounding + w.structured + w.tim_alignment
            self.assertAlmostEqual(total, 1.0, places=5, msg=name)


if __name__ == "__main__":
    unittest.main()
