from __future__ import annotations

from dataclasses import dataclass

from nutonic_pro_gradio_demo.client import NutonicServerClient
from nutonic_pro_gradio_demo.models import ProJobStatusOut, ProVlmImageRef


@dataclass(frozen=True)
class FetchedImage:
    role: str
    mime: str | None
    width: int | None
    height: int | None
    bytes: bytes


def fetch_vlm_images(*, client: NutonicServerClient, job: ProJobStatusOut, bearer_token: str | None = None) -> list[FetchedImage]:
    payload = job.on_device_payload
    if payload is None or not payload.vlm_image_set:
        return []

    out: list[FetchedImage] = []
    for ref in payload.vlm_image_set:
        b = _fetch_ref_bytes(client=client, job_id=job.job_id, ref=ref, bearer_token=bearer_token)
        out.append(
            FetchedImage(
                role=ref.role,
                mime=ref.mime,
                width=ref.width,
                height=ref.height,
                bytes=b,
            )
        )
    return out


def _fetch_ref_bytes(*, client: NutonicServerClient, job_id: str, ref: ProVlmImageRef, bearer_token: str | None) -> bytes:
    url = ref.url or ref.inline_ref
    if url:
        return client.get_bytes_by_url(url)
    if ref.artifact_id:
        return client.get_artifact(job_id=job_id, artifact_id=ref.artifact_id, bearer_token=bearer_token)
    raise ValueError(f"VLM image ref {ref.role!r} has no url/inline_ref/artifact_id")

