from __future__ import annotations

from dataclasses import dataclass
from threading import BoundedSemaphore, Thread
from typing import Any

import httpx

from nutonic_server.inference_client import InferenceClient, InferenceClientConfig
from nutonic_server.pro_jobs_store import ProJobRecord, ProJobStore
from nutonic_server.settings import Settings


@dataclass(frozen=True)
class OriginProbe:
    name: str
    url: str
    required: bool


class ProJobRunner:
    def __init__(self, *, settings: Settings, store: ProJobStore) -> None:
        self._settings = settings
        self._store = store
        self._semaphore = BoundedSemaphore(max(1, int(settings.pro_max_concurrent_jobs)))
        self._threads: dict[str, Thread] = {}

    def submit(self, job_id: str) -> None:
        if job_id in self._threads and self._threads[job_id].is_alive():
            return
        thread = Thread(target=self._run_job_guarded, args=(job_id,), daemon=True, name=f"pro-job-{job_id[:8]}")
        self._threads[job_id] = thread
        thread.start()

    def _run_job_guarded(self, job_id: str) -> None:
        with self._semaphore:
            try:
                self._run_job(job_id)
            except Exception as exc:
                self._store.fail(job_id, error_class=classify_error(exc), error_detail=str(exc))

    def _run_job(self, job_id: str) -> None:
        job = self._store.get_job(job_id)
        if job is None or job.status != "queued":
            return
        running = self._store.transition(job_id, expected={"queued"}, status="running", progress_pct=5)
        if running is None:
            return
        if self._cancel_if_requested(job_id):
            return

        hmac_secret = self._settings.inference_hmac_secret.strip() or None
        cfg = InferenceClientConfig(hmac_secret=hmac_secret)
        with InferenceClient(config=cfg) as ic:
            probe_errors = self._probe_required_origins(ic)
            if probe_errors:
                self._store.fail(job_id, error_class="worker_unreachable", error_detail="; ".join(probe_errors))
                return
            self._store.update_progress(job_id, progress_pct=20)
            if self._cancel_if_requested(job_id):
                return

            materialization_summary: dict[str, Any] | None = None
            materialization_id: str | None = None
            cache_key: str | None = None
            artifacts: list[dict[str, Any]] = []

            pro_url = self._settings.pro_materialization_service_url.strip()
            if pro_url:
                mat = ic.post_json(
                    f"{pro_url.rstrip('/')}/internal/v1/materialize",
                    json_body=_materialization_request(job),
                    read_timeout_s=120.0,
                )
                materialization_summary = summarize_materialize_worker_response(mat)
                materialization_id = str(mat.get("materialization_id") or "") or None
                cache_key = str(mat.get("cache_key") or "") or None
                artifacts.extend(_artifact_refs_from_materialization(job, mat))
            else:
                materialization_summary = {"mode": "no_worker_configured"}

            self._store.update_progress(job_id, progress_pct=80)
            if self._cancel_if_requested(job_id):
                return
            self._store.complete(
                job_id,
                artifacts=artifacts,
                materialization_summary=materialization_summary,
                materialization_id=materialization_id,
                cache_key=cache_key,
            )

    def _probe_required_origins(self, ic: InferenceClient) -> list[str]:
        errors: list[str] = []
        for origin in _origin_probes(self._settings):
            ok = ic.probe_health_origin(origin.url)
            if origin.required and not ok:
                errors.append(f"{origin.name} health probe failed")
        return errors

    def _cancel_if_requested(self, job_id: str) -> bool:
        current = self._store.get_job(job_id)
        if current is None:
            return True
        if current.status == "cancelled":
            return True
        if current.cancel_requested and current.status == "running":
            self._store.transition(job_id, expected={"running"}, status="cancelled", progress_pct=current.progress_pct)
            return True
        return False


def classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "no items found" in msg or "empty search" in msg:
        return "stac_no_coverage"
    if "cloud" in msg and "threshold" in msg:
        return "stac_cloud_ceiling"
    if isinstance(exc, httpx.TimeoutException):
        return "worker_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "worker_unreachable"
    if isinstance(exc, httpx.HTTPStatusError):
        return "worker_error"
    if isinstance(exc, ValueError):
        return "input_validation"
    return "internal"


def summarize_materialize_worker_response(data: dict[str, Any]) -> dict[str, Any]:
    rm = data.get("run_manifest") or {}
    slim_rm = {
        k: rm[k]
        for k in (
            "mapbox_center_mode",
            "mapbox_attribution",
            "bbox_wgs84",
            "vlm_canvas",
            "s2_asset_mapping_version",
        )
        if isinstance(rm, dict) and k in rm
    }
    artifacts: list[dict[str, Any]] = []
    for artifact in data.get("vlm_artifacts") or []:
        if isinstance(artifact, dict):
            artifacts.append({k: artifact[k] for k in ("role", "sha256", "mime", "width", "height") if k in artifact})
    out: dict[str, Any] = {
        "materialization_id": data.get("materialization_id"),
        "cache_key": data.get("cache_key"),
        "run_manifest": slim_rm,
        "vlm_artifacts": artifacts,
    }
    tim_payload = data.get("tim_payload")
    if isinstance(tim_payload, dict):
        out["tim_payload"] = {
            "branch": tim_payload.get("branch"),
            "modalities_keys": tim_payload.get("modalities_keys"),
            "has_npz": bool(tim_payload.get("npz_base64")),
        }
    return out


def _materialization_request(job: ProJobRecord) -> dict[str, Any]:
    params = dict(job.request_params)
    request = {
        "latitude": params.get("center_lat"),
        "longitude": params.get("center_lon"),
        "bbox_half_km": params.get("bbox_half_km", 5.0),
        "mapbox_zoom": params.get("mapbox_zoom", 12),
        "enable_tim": params.get("enable_tim", False),
        "tim_branch": params.get("tim_branch", "RGB_mapbox"),
        "vlm_contract_id": params.get("vlm_contract_id", "nutonic.pro.vlm.v1_512"),
        "sentinel_fetch_mode": params.get("sentinel_fetch_mode", "MINIMAL_RGB"),
        "analysis_profile": job.analysis_profile,
    }
    for key in ("datetime_interval", "scene_id_t0", "scene_id_t1"):
        if params.get(key):
            request[key] = params[key]
    return request


def _artifact_refs_from_materialization(job: ProJobRecord, data: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for i, artifact in enumerate(data.get("vlm_artifacts") or []):
        if not isinstance(artifact, dict):
            continue
        role = str(artifact.get("role") or f"artifact_{i}")
        mime_type = str(artifact.get("mime") or "application/octet-stream")
        kind = _artifact_kind(mime_type)
        refs.append(
            {
                "artifact_id": role,
                "kind": kind,
                "mime_type": mime_type,
                "size_bytes": None,
                "profile": job.analysis_profile,
            }
        )
    return refs


def _artifact_kind(mime_type: str) -> str:
    if mime_type == "application/geo+json":
        return "geojson"
    if "/" in mime_type:
        return mime_type.split("/", 1)[1]
    return "binary"


def _origin_probes(settings: Settings) -> list[OriginProbe]:
    required = set(settings.pro_required_origin_names())
    optional = set(settings.pro_optional_origin_names())
    specs = [
        ("inference_worker", settings.inference_worker_base_url.strip()),
        ("pro_materialization", settings.pro_materialization_service_url.strip()),
    ]
    probes: list[OriginProbe] = []
    for name, url in specs:
        if not url:
            continue
        is_required = name in required or (name not in optional and name == "pro_materialization")
        probes.append(OriginProbe(name=name, url=url, required=is_required))
    return probes
