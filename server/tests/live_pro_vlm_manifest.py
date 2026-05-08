"""Mirror of Kotlin ``verifyModelBytes`` in ``nutonic/shared/.../vlm/ProOnDeviceVlm.kt`` for live download tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

DEFAULT_CONTRACT_ID = "nutonic.pro.vlm.v1_512_s2_only"


@dataclass(frozen=True)
class ProVlmModelManifestLike:
    model_bundle_id: str
    revision: str
    download_url: str
    sha256: str
    size_bytes: int
    runtime: str
    contract_ids: Sequence[str] = ()


def verify_model_bytes_like_on_device_kotlin(
    manifest: ProVlmModelManifestLike,
    body: bytes,
) -> str | None:
    """Return an error string, or ``None`` if verification passes (Kotlin parity)."""
    if manifest.size_bytes >= 0 and len(body) != manifest.size_bytes:
        return f"Downloaded model size mismatch for {manifest.model_bundle_id}"
    expected = manifest.sha256.strip().lower()
    if not expected:
        return "Model manifest is missing sha256"
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        return f"Downloaded model sha256 mismatch for {manifest.model_bundle_id}"
    ids = list(manifest.contract_ids)
    if not ids:
        return "Model manifest is missing supported contract_ids"
    if DEFAULT_CONTRACT_ID not in ids:
        return f"Model manifest does not support {DEFAULT_CONTRACT_ID}"
    return None
