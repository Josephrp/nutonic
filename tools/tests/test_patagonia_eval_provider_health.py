"""Tests for the TiM provider-health gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from patagonia_eval_provider_health import aggregate, assess_tim_row  # noqa: E402


def _good_payload(lat: float, lon: float) -> dict:
    return {
        "tim_modality_outputs": {
            "Coordinates": {"decoded_latitude": lat + 0.05, "decoded_longitude": lon + 0.05},
            "LULC": {"class_fractions": {"trees": 0.6, "water": 0.4}},
        },
        "profile_analytics": {
            "land_transition": {
                "top_transitions": [
                    {"from": "trees", "to": "bare_ground", "count": 5, "pct": 4.0, "delta": -0.04}
                ],
                "class_distribution": [
                    {"label": "trees", "fraction": 0.6},
                    {"label": "water", "fraction": 0.4},
                ],
            }
        },
    }


class TestProviderHealth(unittest.TestCase):
    def test_missing_payload(self) -> None:
        h = assess_tim_row(
            target_id="t1",
            tim_compact=None,
            requested_lat=-50.0,
            requested_lon=-72.0,
            profile="land_use_change",
        )
        self.assertEqual(h.status, "missing")
        self.assertIn("no_tim_payload", h.flags)

    def test_good_row_passes_gate(self) -> None:
        h = assess_tim_row(
            target_id="t1",
            tim_compact=_good_payload(-50.0, -72.0),
            requested_lat=-50.0,
            requested_lon=-72.0,
            profile="land_use_change",
        )
        self.assertEqual(h.status, "good", h.detail)
        self.assertEqual(h.flags, ())

    def test_drift_only_marks_borderline(self) -> None:
        payload = _good_payload(0.0, 0.0)  # decoded near 0,0 but requested -50,-72 → huge drift
        h = assess_tim_row(
            target_id="t2",
            tim_compact=payload,
            requested_lat=-50.0,
            requested_lon=-72.0,
            profile="land_use_change",
        )
        self.assertEqual(h.status, "degenerate")
        self.assertTrue(any(f.startswith("coord_drift") for f in h.flags))
        assert h.drift_km is not None
        self.assertGreater(h.drift_km, 250.0)

    def test_empty_body_with_zero_samples_is_degenerate(self) -> None:
        payload = {
            "tim_modality_outputs": {
                "Coordinates": {"decoded_latitude": -50.05, "decoded_longitude": -72.05},
                "NDVI": {"sample": [0.0, 0.0, 0.0]},
            },
            "profile_analytics": {
                "land_transition": {"transition_matrix": [], "top_transitions": []}
            },
        }
        h = assess_tim_row(
            target_id="t3",
            tim_compact=payload,
            requested_lat=-50.0,
            requested_lon=-72.0,
            profile="land_use_change",
        )
        self.assertEqual(h.status, "degenerate", h.detail)

    def test_aggregate_summary(self) -> None:
        rows = [
            assess_tim_row(
                target_id="g1",
                tim_compact=_good_payload(-50.0, -72.0),
                requested_lat=-50.0,
                requested_lon=-72.0,
                profile="land_use_change",
            ),
            assess_tim_row(
                target_id="m1",
                tim_compact=None,
                requested_lat=-50.0,
                requested_lon=-72.0,
                profile="land_use_change",
            ),
        ]
        agg = aggregate(rows)
        self.assertEqual(agg["n_rows"], 2)
        self.assertEqual(agg["status_counts"]["good"], 1)
        self.assertEqual(agg["status_counts"]["missing"], 1)
        self.assertEqual(agg["verdict"], "ok")


if __name__ == "__main__":
    unittest.main()
