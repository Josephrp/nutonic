"""Unit tests for ``patagonia_eval_dynamic_world`` (no Earth Engine calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_dynamic_world import (  # noqa: E402
    chip_transform_web_mercator,
    stac_meta_to_ee_filter_dates,
)


class TestDynamicWorldHelpers(unittest.TestCase):
    def test_stac_meta_to_ee_filter_dates_midnight_utc_window(self) -> None:
        lo, hi, tag = stac_meta_to_ee_filter_dates({"datetime": "2024-06-15T14:30:00Z"})
        self.assertEqual(tag, "stac_item_day")
        self.assertEqual(lo, "2024-06-15")
        self.assertEqual(hi, "2024-06-16")

    def test_chip_transform_web_mercator_shape(self) -> None:
        crs, aff = chip_transform_web_mercator(-72.0, -50.0, -71.9, -49.9, width=64, height=48)
        self.assertEqual(crs, "EPSG:3857")
        self.assertEqual(len(aff), 6)
        self.assertTrue(all(isinstance(x, float) for x in aff))


if __name__ == "__main__":
    unittest.main()
