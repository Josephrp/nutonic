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


def test_change_profiles_emit_stable_sections() -> None:
    assert "burn_change" in build_profile_analytics("wildfire", {}, None)
    assert "water_change" in build_profile_analytics("flood_pulse", {}, None)
    assert "land_transition" in build_profile_analytics("land_use_change", {}, None)
