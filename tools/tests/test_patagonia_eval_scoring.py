"""Unit tests for Patagonia multimodal eval scoring (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Repo root: tools/tests/ -> parents[1] == tools; parents[2] == nutonic
REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))
if str(REPO / "data" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "data" / "scripts"))

from evaluate_vlm_patagonia import default_patagonia_targets  # noqa: E402
from patagonia_eval_scoring import (  # noqa: E402
    iou_xyxy,
    parse_predicted_boxes,
    score_patagonia_multimodal,
)


class TestPatagoniaScoring(unittest.TestCase):
    def test_iou_identical(self) -> None:
        self.assertAlmostEqual(iou_xyxy((0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 1.0)), 1.0, places=5)

    def test_iou_disjoint(self) -> None:
        self.assertAlmostEqual(iou_xyxy((0.0, 0.0, 0.5, 0.5), (0.5, 0.5, 1.0, 1.0)), 0.0, places=5)

    def test_parse_json_array(self) -> None:
        text = 'Analysis\n[{"label": "water", "bbox": [0.1, 0.2, 0.5, 0.6]}]\n'
        boxes = parse_predicted_boxes(text)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["label"], "water")

    def test_composite_with_gold(self) -> None:
        target = default_patagonia_targets()[0]
        gold = [{"label": "water", "bbox": [0.0, 0.0, 1.0, 1.0], "source": "sentinel2_scl"}]
        caption = '[{"label":"ocean","bbox":[0.05,0.05,0.95,0.95]}]'
        out = score_patagonia_multimodal(
            caption,
            target,
            threshold=0.5,
            gold_boxes=gold,
            score_mode="composite",
            pass_metric="composite",
        )
        self.assertIn("composite", out)
        self.assertGreater(out["grounding"]["score"] or 0, 0.5)


if __name__ == "__main__":
    unittest.main()
