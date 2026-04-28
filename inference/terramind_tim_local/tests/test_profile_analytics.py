from __future__ import annotations

from nutonic_terramind_tim_local.serialize import build_profile_analytics


def test_oceanscout_profile_analytics_claim_safe_shape() -> None:
    out = build_profile_analytics(
        "oceanscout_ship_detection",
        {"LULC": {"kind": "class_logits"}},
        {"s2_stac": {"stac_item_id": "S2A_TEST", "stac_datetime": "2026-01-01T00:00:00Z", "eo_cloud_cover": 4.2}},
    )
    assert out["profile"] == "oceanscout_ship_detection"
    assert out["evidence_level"] == "tim_pseudosar_plus_lulc"
    assert out["observation_coverage"]["normalization"] == "valid_observation_count"
    assert "illegal" not in " ".join(out["notices"]).lower()
    assert out["shoreline_policy"]["version"] == "1.0"
    assert out["scene_provenance"]["item_id"] == "S2A_TEST"


def test_oceanscout_profile_analytics_uses_tim_samples_for_coverage() -> None:
    out = build_profile_analytics(
        "oceanscout_ship_detection",
        {"LULC": {"logits": {"sample": [0.0, 0.5, 1.0, -1.0]}}},
        {
            "s2_stac": {
                "stac_item_id": "S2A_TEST",
                "stac_datetime": "2026-01-01T00:00:00Z",
                "eo_cloud_cover": 25.0,
            },
        },
    )

    assert out["observation_coverage"]["valid_observation_count"] == 4
    assert out["observation_coverage"]["cloud_masked_count"] == 1
    assert out["detection_score_summary"]["candidate_signal_pct"] == 50.0
    assert out["confidence"]["bins"] == {"low": 1, "medium": 1, "high": 2}
    assert out["vessel_candidates"][0]["claim_safety"] == "presence_indicator_not_legal_assertion"


def test_change_profiles_emit_stable_sections() -> None:
    assert "burn_change" in build_profile_analytics("wildfire", {}, None)
    assert "water_change" in build_profile_analytics("flood_pulse", {}, None)
    assert "land_transition" in build_profile_analytics("land_use_change", {}, None)


def test_change_profiles_use_tim_samples_for_metrics() -> None:
    outputs = {"LULC": {"classes": {"sample": [0.0, 1.0, 1.0, 2.0]}}}

    wildfire = build_profile_analytics("wildfire", outputs, None)
    flood = build_profile_analytics("flood_pulse", outputs, None)
    land = build_profile_analytics("land_use_change", outputs, None)

    assert wildfire["burn_change"]["changed_area_pct"] == 75.0
    assert wildfire["burn_change"]["hotspot_count"] == 1
    assert wildfire["burn_change"]["heat_clusters"][0]["confidence"] == "high"
    assert flood["water_change"]["expanded_area_pct"] == 25.0
    assert flood["water_change"]["affected_area_proxy_pct"] == 75.0
    assert land["land_transition"]["raw_counts_total"] == 4
    assert land["land_transition"]["class_distribution"][0] == {
        "value": 1,
        "count": 2,
        "pct": 50.0,
    }
    assert land["land_transition"]["temporal_comparison_available"] is True
    assert land["land_transition"]["top_transitions"][0]["from"] == "0"
