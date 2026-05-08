"""Token grid reshape for TiM materialization (torch only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.geoguessr_materialize import (
    _codebook_upper,
    _ids_bhw_from_block,
    _safe_stem,
    _tensor_bchw_to_rgb_u8,
    materialize_tim_row,
)


def test_safe_stem_replaces_at() -> None:
    assert _safe_stem("tok_lulc@224") == "tok_lulc_at_224"


def test_tensor_bchw_s2_rgb_order_uses_b321() -> None:
    # 12 bands: make RED high on band 3, others low → red-ish pixel
    t = torch.zeros(1, 12, 2, 2)
    t[0, 3, 0, 0] = 8000.0
    t[0, 2, 0, 0] = 500.0
    t[0, 1, 0, 0] = 500.0
    rgb = _tensor_bchw_to_rgb_u8(t)
    assert rgb.shape == (2, 2, 3)
    assert rgb[0, 0, 0] > rgb[0, 0, 2]


def test_codebook_upper_fsq_hyphen_string_uses_level_product() -> None:
    class _Q:
        _levels = __import__("torch").tensor([7, 5, 5, 5, 5], dtype=torch.int32)

    class _T:
        codebook_size = "7-5-5-5-5"
        quantize = _Q()

    assert _codebook_upper(_T()) == 7 * 5 * 5 * 5 * 5


def test_ids_bhw_from_block_196_tokens() -> None:
    t = torch.arange(196, dtype=torch.float32).view(1, 196)
    ids = _ids_bhw_from_block({"tensor": t}, torch.device("cpu"))
    assert ids.shape == (1, 14, 14)
    assert ids.dtype == torch.int64


def test_materialize_tim_row_writes_profile_artifact_index(tmp_path: Path) -> None:
    class _Model(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.zeros(1))

    manifest = materialize_tim_row(
        _Model(),
        {"untok_sen2l2a@224": {"tensor": torch.ones(1, 12, 4, 4)}},
        tmp_path / "row",
        analysis_profile="oceanscout_ship_detection",
        profile_analytics={
            "observation_coverage": {"valid_observation_count": 4, "cloud_masked_count": 1},
            "vessel_candidates": [{"candidate_id": "c1", "center_lat": 1.0, "center_lon": 2.0}],
        },
        inputs_aux={
            "scene_provenance": {
                "t1": {"item_id": "S2_A", "datetime": "2024-01-01T00:00:00Z", "cloud_pct": 2.0}
            }
        },
    )
    index_path = manifest["profile_artifact_index"]["path"]
    payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert payload["analysis_profile"] == "oceanscout_ship_detection"
    assert payload["scene_provenance"]["t1"]["item_id"] == "S2_A"
    assert {asset["artifact_id"] for asset in payload["assets"]} >= {
        "observation_coverage",
        "vessel_candidates",
        "vessel_overlay",
    }
    assert payload["overlays"][0]["kind"] == "vessel_candidate_overlay"
