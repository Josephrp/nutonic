"""
Live Hugging Face download test mirroring on-device PRO VLM acquisition.

The Kotlin client downloads ``download_url`` bytes with ``httpx``/Ktor, then runs the same
checks as ``verifyModelBytes`` in ``nutonic/shared/src/commonMain/kotlin/com/nutonic/vlm/ProOnDeviceVlm.kt``.

This test is **opt-in** so CI stays offline unless you set ``RUN_LIVE_HF_LFM_DOWNLOAD=1``.

Run::

    set RUN_LIVE_HF_LFM_DOWNLOAD=1
    python -m pytest server/tests/test_live_hf_lfm_model_download.py -v

Optional strict pin (after upstream moves ``main``)::

    set NUTONIC_LIVE_LFM_HF_URL=https://huggingface.co/LiquidAI/LFM2.5-VL-450M/resolve/main/config.json
    set NUTONIC_LIVE_LFM_EXPECTED_SIZE=12345
    set NUTONIC_LIVE_LFM_EXPECTED_SHA256=abc...   # lowercase hex
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

import httpx
import pytest

from live_pro_vlm_manifest import (
    ProVlmModelManifestLike,
    verify_model_bytes_like_on_device_kotlin,
)

# Default: small public JSON from the same HF repo the LFM-VL hint service uses (see ``liquid_hub_ids.py``).
_DEFAULT_LFM_HF_URL = (
    "https://huggingface.co/LiquidAI/LFM2.5-VL-450M/resolve/main/config.json"
)


def test_verify_rejects_wrong_size_or_hash() -> None:
    sha_ab = "fb8e20fc2e4c3f248c60c39bd652f3c1347298bb977b8b4d5903b85055620603"
    manifest = ProVlmModelManifestLike(
        model_bundle_id="t",
        revision="r",
        download_url="https://example.invalid/unused",
        sha256=sha_ab,
        size_bytes=2,
        runtime="test",
        contract_ids=("nutonic.pro.vlm.v1_512_s2_only",),
    )
    assert verify_model_bytes_like_on_device_kotlin(manifest, b"ab") is None
    assert verify_model_bytes_like_on_device_kotlin(manifest, b"a") is not None
    sha_a = "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
    bad = ProVlmModelManifestLike(
        model_bundle_id="t",
        revision="r",
        download_url="https://example.invalid/unused",
        sha256="b" * 64,
        size_bytes=1,
        runtime="test",
        contract_ids=("nutonic.pro.vlm.v1_512_s2_only",),
    )
    assert verify_model_bytes_like_on_device_kotlin(bad, b"a") is not None
    good_one_byte = replace(bad, sha256=sha_a)
    assert verify_model_bytes_like_on_device_kotlin(good_one_byte, b"a") is None

    wrong_contract = replace(
        good_one_byte,
        contract_ids=("other.contract",),
    )
    assert verify_model_bytes_like_on_device_kotlin(wrong_contract, b"a") is not None
    missing_contracts = replace(good_one_byte, contract_ids=())
    assert verify_model_bytes_like_on_device_kotlin(missing_contracts, b"a") is not None


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_HF_LFM_DOWNLOAD", "").strip() != "1",
    reason="Set RUN_LIVE_HF_LFM_DOWNLOAD=1 to run live Hugging Face download test",
)
def test_live_download_small_lfm_artifact_from_huggingface() -> None:
    """
    Same transport as on-device: plain HTTPS GET to a full URL (here HF ``/resolve/``),
    then Kotlin-identical size + sha256 + contract_id gate.
    """
    url = os.environ.get("NUTONIC_LIVE_LFM_HF_URL", _DEFAULT_LFM_HF_URL).strip()
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "NuTonic-live-test/1.0"})
    response.raise_for_status()
    body = response.content
    assert len(body) > 0, "empty body"

    cfg = json.loads(body.decode("utf-8"))
    assert isinstance(cfg, dict)
    # LFM-VL stack config markers (file is part of the same model repo the app targets).
    assert "model_type" in cfg or "architectures" in cfg, f"unexpected config keys: {list(cfg)[:20]}"

    pinned_size = os.environ.get("NUTONIC_LIVE_LFM_EXPECTED_SIZE", "").strip()
    pinned_sha = os.environ.get("NUTONIC_LIVE_LFM_EXPECTED_SHA256", "").strip().lower()
    if pinned_size and pinned_sha:
        size_i = int(pinned_size)
        sha = pinned_sha
    else:
        size_i = len(body)
        sha = __import__("hashlib").sha256(body).hexdigest()

    manifest = ProVlmModelManifestLike(
        model_bundle_id="live.hf.LiquidAI.LFM2.5-VL-450M.config",
        revision="main",
        download_url=url,
        sha256=sha,
        size_bytes=size_i,
        runtime="hf_resolve_get",
        contract_ids=("nutonic.pro.vlm.v1_512_s2_only",),
    )
    err = verify_model_bytes_like_on_device_kotlin(manifest, body)
    assert err is None, err
