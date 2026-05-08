"""Tests for bi-temporal SCL delta gold extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_gold import SCL_BARE, gold_boxes_from_scl, gold_boxes_from_scl_delta  # noqa: E402


class TestGoldDelta(unittest.TestCase):
    def test_shape_mismatch_returns_empty(self) -> None:
        a = np.zeros((8, 8), dtype=np.uint8)
        b = np.zeros((9, 9), dtype=np.uint8)
        self.assertEqual(gold_boxes_from_scl_delta(a, b, category="marine_reserve"), [])

    def test_water_emerges(self) -> None:
        from patagonia_eval_gold import SCL_VEG, SCL_WATER

        h, w = 48, 48
        scl_e = np.full((h, w), SCL_VEG, dtype=np.uint8)
        scl_l = np.full((h, w), SCL_VEG, dtype=np.uint8)
        scl_l[15:30, 15:30] = SCL_WATER
        boxes = gold_boxes_from_scl_delta(scl_e, scl_l, category="marine_reserve")
        water_boxes = [b for b in boxes if b["label"] == "water"]
        self.assertTrue(water_boxes)
        self.assertTrue(any("delta" in str(b.get("source", "")) for b in water_boxes))

    def test_steppe_category_extracts_bare_state_gold(self) -> None:
        h, w = 64, 64
        scl = np.zeros((h, w), dtype=np.uint8)
        scl[10:50, 10:50] = SCL_BARE
        boxes = gold_boxes_from_scl(scl, category="steppe_annual_burn_context")
        bare = [b for b in boxes if b["label"] == "bare"]
        self.assertTrue(bare)


if __name__ == "__main__":
    unittest.main()
