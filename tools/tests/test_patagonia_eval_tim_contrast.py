"""Tests for TiM contrastive perturbations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_tim_contrast import (  # noqa: E402
    contrast_caption_responsiveness,
    flip_tim_modality_numeric_samples,
)


class TestTimContrast(unittest.TestCase):
    def test_flip_negates_samples(self) -> None:
        compact = {"tim_modality_outputs": {"NDVI": {"sample": [0.5, -1.0]}}, "profile_analytics": {}}
        flipped = flip_tim_modality_numeric_samples(compact)
        self.assertEqual(flipped["tim_modality_outputs"]["NDVI"]["sample"], [-0.5, 1.0])
        self.assertEqual(compact["tim_modality_outputs"]["NDVI"]["sample"], [0.5, -1.0])

    def test_responsiveness_identical_low(self) -> None:
        s, _ = contrast_caption_responsiveness("hello tim", "hello tim")
        self.assertLessEqual(s, 0.05)

    def test_responsiveness_different_high(self) -> None:
        s, _ = contrast_caption_responsiveness("rising ndvi trend", "falling ndvi trend")
        self.assertGreaterEqual(s, 0.2)


if __name__ == "__main__":
    unittest.main()
