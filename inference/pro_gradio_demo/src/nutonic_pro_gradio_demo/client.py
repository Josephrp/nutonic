from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from nutonic_pro_gradio_demo.models import ProJobCreateIn, ProJobCreateOut, ProJobStatusOut, ProVlmModelManifest
from nutonic_pro_gradio_demo.settings import Settings


def _is_absolute_url(url: str) -> bool:
    try:
        return bool(urlparse(url).scheme)
    except Exception:
        return False


def _resolve_url(*, origin: str, url_or_path: str) -> str:
    if _is_absolute_url(url_or_path):
        return url_or_path
    if not origin:
        raise ValueError("NUTONIC_SERVER_ORIGIN is required to resolve relative URLs")
    return urljoin(origin.rstrip("/") + "/", url_or_path.lstrip("/"))


@dataclass(frozen=True)
class PollProgress:
    job_id: str
    status: str
    progress_pct: int | None
    status_reason: str | None


class NutonicServerClient:
    def __init__(self, settings: Settings) -> None:
        origin = settings.nutonic_server_origin.strip()
        if origin:
            origin = origin.rstrip("/")
        self._origin = origin
        self._timeout = httpx.Timeout(settings.http_timeout_seconds)
        self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)

    @property
    def origin(self) -> str:
        return self._origin

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        if not self._origin:
            raise ValueError("NUTONIC_SERVER_ORIGIN must be set")
        return self._origin + path

    def post_pro_job(self, body: ProJobCreateIn) -> ProJobCreateOut:
        r = self._client.post(self._url("/api/v1/pro/jobs"), json=body.model_dump(mode="json"))
        r.raise_for_status()
        return ProJobCreateOut.model_validate(r.json())

    def get_pro_job(self, job_id: str) -> ProJobStatusOut:
        r = self._client.get(self._url(f"/api/v1/pro/jobs/{job_id}"))
        r.raise_for_status()
        return ProJobStatusOut.model_validate(r.json())

    def get_artifact(self, *, job_id: str, artifact_id: str) -> bytes:
        r = self._client.get(self._url(f"/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}"))
        r.raise_for_status()
        return r.content

    def get_bytes_by_url(self, url_or_path: str) -> bytes:
        url = _resolve_url(origin=self._origin, url_or_path=url_or_path)
        r = self._client.get(url)
        r.raise_for_status()
        return r.content

    def get_vlm_model_manifest(self) -> ProVlmModelManifest:
        r = self._client.get(self._url("/api/v1/pro/vlm/model-manifest"))
        r.raise_for_status()
        return ProVlmModelManifest.model_validate(r.json())

    def poll_until_terminal(
        self,
        *,
        job_id: str,
        poll_interval_seconds: float,
        poll_timeout_seconds: float,
        on_progress: callable | None = None,
    ) -> ProJobStatusOut:
        import time

        deadline = time.time() + poll_timeout_seconds
        last: ProJobStatusOut | None = None
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"Timed out polling PRO job {job_id}")
            status = self.get_pro_job(job_id)
            last = status
            if on_progress is not None:
                try:
                    on_progress(
                        PollProgress(
                            job_id=status.job_id,
                            status=status.status,
                            progress_pct=status.progress_pct,
                            status_reason=status.status_reason,
                        )
                    )
                except Exception:
                    pass
            if status.status in {"completed", "failed", "cancelled"}:
                return status
            time.sleep(max(0.2, poll_interval_seconds))


def pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)

