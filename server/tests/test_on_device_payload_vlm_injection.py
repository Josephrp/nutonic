"""On-device payload must expose TiM + run_manifest VLM injection even when brief fusion is absent."""

from __future__ import annotations

from nutonic_server.main import _on_device_payload
from nutonic_server.schemas import ProArtifactRef
from nutonic_server.settings import Settings


def test_on_device_payload_includes_tim_without_brief_summary() -> None:
    settings = Settings()
    artifacts = [
        ProArtifactRef(
            artifact_id="sentinel_fc",
            kind="image",
            mime_type="image/png",
            size_bytes=42,
            profile="brief_only",
            contract_id="nutonic.pro.vlm.v1_512_s2_only",
            role="sentinel_fc",
            category="vlm_image",
            required_for_profile=True,
            download_url="/api/v1/pro/jobs/j1/artifacts/sentinel_fc",
        ),
    ]
    mat = {
        "materialization_id": "mid",
        "cache_key": "ck",
        "run_manifest": {"bbox_wgs84": {"west": -1.0, "south": -2.0, "east": 3.0, "north": 4.0}},
        "tim_summary": {"branch": "S2L2A_full", "modalities_keys": ["S2L2A"], "has_npz": True},
        # brief_summary intentionally missing (LFMs unavailable or skipped).
    }
    out = _on_device_payload(settings, mat, artifacts, artifacts, job_analysis_profile="brief_only")
    assert out is not None
    assert out.brief_sections == []
    assert out.confidence_summary is None
    inj = out.vlm_prompt_injection or {}
    assert inj.get("vlm_prompt_style") == "sft_production_analysis"
    prod = str(inj.get("production_tim_user_prompt") or "")
    assert "Production-like analysis input:" in prod
    assert "brief_only" in prod
    block = str(inj.get("tim_context_block") or "")
    assert "TerraMind / TiM context" in block
    assert "S2L2A_full" in block
    assert '"branch":' in block
    assert "<redacted>" in block
    assert inj["run_manifest"]["bbox_wgs84"]["east"] == 3.0
