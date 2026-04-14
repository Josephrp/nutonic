from __future__ import annotations

import json
from pathlib import Path

import httpx

from tools.batch_streetview_hints import BatchConfig, REPO_ROOT, run_batch


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if request.method == "GET" and p.rstrip("/").endswith("/health"):
        host = (request.url.host or "").lower()
        if host.startswith("pano"):
            return httpx.Response(
                200,
                json={"status": "ok", "streetview_provider": "stub", "google_configured": "no"},
            )
        if host.startswith("lfm"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "lfm_backend": "stub",
                    "lfm_backend_config": "stub",
                    "model_id": "stub-model",
                },
            )
        if host.startswith("sat"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "lfm_satellite_backend": "stub",
                    "lfm_satellite_backend_config": "stub",
                    "model_id": "sat-fixture",
                },
            )
        return httpx.Response(200, json={"status": "ok"})
    if request.method == "POST" and p.endswith("/v1/panos/sample"):
        body = json.loads(request.content.decode())
        n = int(body["count"])
        rid = body["request_id"]
        frames = []
        for i in range(n):
            frames.append(
                {
                    "pano_id": f"stub-{i}",
                    "heading_deg": float(i * 40),
                    "pitch_deg": 0.0,
                    "image_base64": "abc",
                    "attribution": "stub",
                }
            )
        return httpx.Response(
            200,
            json={"request_id": rid, "frames": frames, "cache_key": "sha256:test", "terms_version": "2026-04"},
        )
    if request.method == "POST" and p.endswith("/v1/suggestions/from_frames"):
        body = json.loads(request.content.decode())
        sug = []
        for i, fr in enumerate(body["frames"]):
            pid = fr.get("pano_id") or f"decoy-{i}"
            sug.append(
                {
                    "text": f"Street-level view {i + 1}; mixed roadside textures without coordinates.",
                    "viewpoint_id": str(pid),
                    "rank": i + 1,
                }
            )
        return httpx.Response(200, json={"suggestions": sug})
    if request.method == "POST" and p.endswith("/v1/infer"):
        return httpx.Response(
            200,
            json={
                "caption": "Ortho still shows vegetation and a road junction.",
                "model_id": "sat-infer",
                "pipeline": "satellite_lfm_vl_specialist",
            },
        )
    return httpx.Response(404, json={"detail": "not found"})


def test_run_batch_writes_streetview_json(tmp_path: Path) -> None:
    catalog = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "assemble_manifest" / "catalog"
    transport = httpx.MockTransport(_handler)
    cfg = BatchConfig(
        catalog_root=catalog,
        poi_root=REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12",
        pano_service_url="http://pano.test",
        lfm_vl_url="http://lfm.test",
        content_version="pytest-sv",
        output_dir=tmp_path,
        poi_limit=1,
        location_ids=frozenset({"asm_fix_a"}),
        location_ids_file=None,
        shuffle_seed=None,
        sv_screenshots_per_location=3,
        lfm_max_frames_per_request=2,
        satellite_caption_service_url=None,
        still_index_path=None,
        useful_hints_dir=None,
        inject_useful_hint_tone=False,
        prompt_template_version="stub-v1",
        enable_narrative_pass=False,
        narrative_service_url=None,
        skip_streetview_hints=False,
        allow_partial=True,
        timeout_sec=30.0,
    )
    with httpx.Client(transport=transport) as client:
        code = run_batch(cfg, client)
    assert code == 0
    out = tmp_path / "streetview" / "asm_fix_a.json"
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["location_id"] == "asm_fix_a"
    assert len(doc["streetview_hint_pack"]) == 3
    assert doc["streetview_assist_narrative"] is None
    pins = doc["model_pins"]
    assert pins["streetview_pano_service"]["stub_jpeg"] is True
    assert pins["lfm_vl_hint_service"]["stub"] is True
    assert pins["lfm_vl_hint_service"]["model_id"] == "stub-model"
    assert "lfm_vl_satellite_caption_service" not in pins


def test_run_batch_satellite_sidecar_and_service_pin(tmp_path: Path) -> None:
    catalog = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "assemble_manifest" / "catalog"
    tiny = tmp_path / "one_pixel.jpg"
    tiny.write_bytes(b"\xff\xd8\xff\xd9")
    still_index = tmp_path / "still_index.json"
    still_index.write_text(
        json.dumps(
            {
                "locations": [
                    {
                        "location_id": "asm_fix_a",
                        "still_bundled_resource": str(tiny.resolve()).replace("\\", "/"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    transport = httpx.MockTransport(_handler)
    cfg = BatchConfig(
        catalog_root=catalog,
        poi_root=REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12",
        pano_service_url="http://pano.test",
        lfm_vl_url="http://lfm.test",
        content_version="pytest-sv-sat",
        output_dir=tmp_path,
        poi_limit=1,
        location_ids=frozenset({"asm_fix_a"}),
        location_ids_file=None,
        shuffle_seed=None,
        sv_screenshots_per_location=2,
        lfm_max_frames_per_request=2,
        satellite_caption_service_url="http://sat.test",
        still_index_path=still_index,
        useful_hints_dir=None,
        inject_useful_hint_tone=False,
        prompt_template_version="stub-v1",
        enable_narrative_pass=False,
        narrative_service_url=None,
        skip_streetview_hints=False,
        allow_partial=True,
        timeout_sec=30.0,
    )
    with httpx.Client(transport=transport) as client:
        assert run_batch(cfg, client) == 0
    doc = json.loads((tmp_path / "streetview" / "asm_fix_a.json").read_text(encoding="utf-8"))
    assert doc["satellite_caption_sidecar"]["caption"].startswith("Ortho still")
    assert doc["model_pins"]["lfm_vl_satellite_caption_service"]["model_id"] == "sat-fixture"
