"""Tests for visual gold YAML loader."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_visual_gold import has_no_local_features, load_visual_gold  # noqa: E402


class TestVisualGold(unittest.TestCase):
    def test_load_default_yaml(self) -> None:
        g = load_visual_gold()
        self.assertIn("pat_namuncura_burdwood", g)

    def test_no_local_features_flag(self) -> None:
        self.assertTrue(has_no_local_features("pat_namuncura_burdwood"))
        self.assertFalse(has_no_local_features("pat_los_alerces_np"))


if __name__ == "__main__":
    unittest.main()
