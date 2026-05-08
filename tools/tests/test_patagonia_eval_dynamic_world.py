"""Unit tests for ``patagonia_eval_dynamic_world`` (no Earth Engine calls)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_dynamic_world import (  # noqa: E402
    chip_transform_web_mercator,
    earth_engine_init_cached,
    ee_project_id,
    reset_earth_engine_init_cache,
    stac_meta_to_ee_filter_dates,
)


class TestEeProjectFromJson(unittest.TestCase):
    def tearDown(self) -> None:
        for k in (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "EE_SERVICE_ACCOUNT_KEY_PATH",
            "GOOGLE_CLOUD_PROJECT",
            "EE_PROJECT_ID",
        ):
            os.environ.pop(k, None)

    def test_project_id_read_from_service_account_json(self) -> None:
        payload = {
            "type": "service_account",
            "project_id": "radioshaq-test",
            "private_key_id": "x",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMII\n-----END PRIVATE KEY-----\n",
            "client_email": "ee@test.iam.gserviceaccount.com",
            "client_id": "1",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(payload, f)
            path = f.name
        try:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
            self.assertEqual(ee_project_id(), "radioshaq-test")
        finally:
            Path(path).unlink(missing_ok=True)


class TestEarthEngineSkip(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("NUTONIC_SKIP_EE_DYNAMIC_WORLD", None)
        reset_earth_engine_init_cache()

    def test_skip_env_short_circuits_without_ee(self) -> None:
        os.environ["NUTONIC_SKIP_EE_DYNAMIC_WORLD"] = "1"
        reset_earth_engine_init_cache()
        ok, diag = earth_engine_init_cached()
        self.assertFalse(ok)
        self.assertEqual(diag.get("reason"), "skipped_env")
        ok2, diag2 = earth_engine_init_cached()
        self.assertFalse(ok2)
        self.assertEqual(diag2.get("reason"), "skipped_env")


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
