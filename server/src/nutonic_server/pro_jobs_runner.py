from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Event, Thread, current_thread
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
        self._shutdown = Event()
        self._dispatcher_thread: Thread | None = None

    def submit(self, job_id: str) -> None:
        if self._shutdown.is_set():
            return
        if job_id in self._threads and self._threads[job_id].is_alive():
            return
        thread = Thread(target=self._run_job_guarded, args=(job_id,), daemon=True, name=f"pro-job-{job_id[:8]}")
        self._threads[job_id] = thread
        thread.start()

    def start(self) -> None:
        if self._dispatcher_thread is not None and self._dispatcher_thread.is_alive():
            return
        self._shutdown.clear()
        self._dispatcher_thread = Thread(target=self._sweep_loop, daemon=True, name="pro-job-sweeper")
        self._dispatcher_thread.start()

    def shutdown(self, *, grace_seconds: float = 30.0) -> None:
        self._shutdown.set()
        if self._dispatcher_thread is not None and self._dispatcher_thread is not current_thread():
            self._dispatcher_thread.join(timeout=max(0.0, min(float(grace_seconds), 5.0)))

        deadline = time.monotonic() + max(0.0, float(grace_seconds))
        for thread in list(self._threads.values()):
            if thread is current_thread() or not thread.is_alive():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def sweep_once(self) -> int:
        self._prune_finished_threads()
        submitted = 0
        for job in self._store.list_queued_jobs(limit=max(10, int(self._settings.pro_max_concurrent_jobs) * 10)):
            if self._shutdown.is_set():
                break
            self.submit(job.job_id)
            submitted += 1
        return submitted

    def cleanup_once(self) -> int:
        return self._store.cleanup_finished(
            ttl_seconds=self._settings.pro_job_ttl_seconds,
            artifact_root=self._settings.pro_artifact_root,
        )

    def _sweep_loop(self) -> None:
        next_cleanup_at = 0.0
        while not self._shutdown.is_set():
            self.sweep_once()
            now = time.monotonic()
            if now >= next_cleanup_at:
                self.cleanup_once()
                next_cleanup_at = now + 900.0
            self._shutdown.wait(max(0.1, float(self._settings.pro_job_poll_interval_seconds)))

    def _prune_finished_threads(self) -> None:
        self._threads = {job_id: thread for job_id, thread in self._threads.items() if thread.is_alive()}

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
            self._store.update_progress(job_id, progress_pct=15)
            if self._cancel_if_requested(job_id):
                return

            materialization_summary: dict[str, Any] | None = None
            materialization_id: str | None = None
            cache_key: str | None = None
            artifacts: list[dict[str, Any]] = []
            tim_summary: dict[str, Any] | None = None
            brief_summary: dict[str, Any] | None = None

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
                artifacts.extend(_artifact_refs_from_materialization(self._settings, job, mat))
                tim_summary = _tim_summary_from_materialization(mat)
            else:
                materialization_summary = {"mode": "no_worker_configured"}
                tim_summary = {"mode": "not_requested"}

            self._store.update_progress(job_id, progress_pct=60)
            if self._cancel_if_requested(job_id):
                return

            brief_url = self._settings.lfm_vl_hint_service_url.strip()
            if brief_url:
                brief = ic.post_json(
                    f"{brief_url.rstrip('/')}/v1/pro/brief/fuse",
                    json_body=_brief_request(job, tim_summary=tim_summary, artifacts=artifacts),
                    read_timeout_s=60.0,
                )
                brief_summary = summarize_brief_worker_response(brief)
                artifacts.append(_persist_brief_artifact(self._settings, job, brief))
            else:
                brief_summary = {"mode": "no_worker_configured"}

            self._store.update_progress(job_id, progress_pct=90)
            if self._cancel_if_requested(job_id):
                return
            if materialization_summary is not None:
                materialization_summary = dict(materialization_summary)
                materialization_summary["tim_summary"] = tim_summary
                materialization_summary["brief_summary"] = brief_summary
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


def summarize_brief_worker_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        k: data[k]
        for k in (
            "executive_summary",
            "key_findings",
            "confidence",
            "recommended_actions",
            "warnings",
            "limitations",
        )
        if k in data
    }


def _tim_summary_from_materialization(data: dict[str, Any]) -> dict[str, Any]:
    tim_payload = data.get("tim_payload")
    if not isinstance(tim_payload, dict):
        return {"mode": "not_available"}
    return {
        "branch": tim_payload.get("branch"),
        "modalities_keys": tim_payload.get("modalities_keys"),
        "has_npz": bool(tim_payload.get("npz_base64")),
    }


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


def _brief_request(
    job: ProJobRecord,
    *,
    tim_summary: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    params = dict(job.request_params)
    return {
        "profile": job.analysis_profile,
        "tim_summary": tim_summary,
        "artifact_refs": [
            {
                "artifact_id": artifact.get("artifact_id"),
                "kind": artifact.get("kind"),
                "mime_type": artifact.get("mime_type"),
                "profile": artifact.get("profile"),
            }
            for artifact in artifacts
        ],
        "jobs": [
            {
                "job_id": job.job_id,
                "profile": job.analysis_profile,
                "center_lat": params.get("center_lat"),
                "center_lon": params.get("center_lon"),
                "summary": tim_summary,
            }
        ],
    }


def _artifact_refs_from_materialization(settings: Settings, job: ProJobRecord, data: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, artifact in enumerate(data.get("vlm_artifacts") or []):
        if not isinstance(artifact, dict):
            continue
        role = str(artifact.get("role") or f"artifact_{i}")
        artifact_id = _unique_artifact_id(_safe_artifact_id(role) or f"artifact_{i}", seen, i)
        mime_type = str(artifact.get("mime") or "application/octet-stream")
        kind = _artifact_kind(mime_type)
        size_bytes = _persist_inline_artifact(
            artifact_root=settings.pro_artifact_root,
            job_id=job.job_id,
            artifact_id=artifact_id,
            mime_type=mime_type,
            inline_base64=artifact.get("inline_base64"),
        )
        refs.append(
            {
                "artifact_id": artifact_id,
                "kind": kind,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "profile": job.analysis_profile,
            }
        )
    return refs


def _persist_brief_artifact(settings: Settings, job: ProJobRecord, data: dict[str, Any]) -> dict[str, Any]:
    artifact_id = "brief_summary"
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    job_dir = Path(settings.pro_artifact_root) / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / f"{artifact_id}.json").write_bytes(encoded)
    return {
        "artifact_id": artifact_id,
        "kind": "brief",
        "mime_type": "application/json",
        "size_bytes": len(encoded),
        "profile": "brief_only",
    }


def _artifact_kind(mime_type: str) -> str:
    if mime_type == "application/geo+json":
        return "geojson"
    if "/" in mime_type:
        return mime_type.split("/", 1)[1]
    return "binary"


def _persist_inline_artifact(
    *,
    artifact_root: str,
    job_id: str,
    artifact_id: str,
    mime_type: str,
    inline_base64: object,
) -> int | None:
    if not isinstance(inline_base64, str) or not inline_base64:
        return None
    try:
        data = base64.b64decode(inline_base64, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid inline_base64 for artifact {artifact_id}") from exc
    job_dir = Path(artifact_root) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / f"{artifact_id}{_extension_for_mime(mime_type)}").write_bytes(data)
    return len(data)


def _safe_artifact_id(raw: str) -> str:
    cleaned = "".join(ch if ch.isascii() and (ch.isalnum() or ch in ("-", "_", ".")) else "_" for ch in raw.strip())
    return cleaned.strip("._-")[:96]


def _unique_artifact_id(candidate: str, seen: set[str], index: int) -> str:
    artifact_id = candidate
    if artifact_id in seen:
        artifact_id = f"{candidate}_{index}"
    seen.add(artifact_id)
    return artifact_id


def _extension_for_mime(mime_type: str) -> str:
    if mime_type == "image/png":
        return ".png"
    if mime_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if mime_type == "application/json":
        return ".json"
    if mime_type == "application/geo+json":
        return ".geojson"
    return ".bin"


def _origin_probes(settings: Settings) -> list[OriginProbe]:
    required = set(settings.pro_required_origin_names())
    optional = set(settings.pro_optional_origin_names())
    specs = [
        ("inference_worker", settings.inference_worker_base_url.strip()),
        ("pro_materialization", settings.pro_materialization_service_url.strip()),
        ("lfm_vl_hint", settings.lfm_vl_hint_service_url.strip()),
    ]
    probes: list[OriginProbe] = []
    for name, url in specs:
        if not url:
            continue
        is_required = name in required or (name not in optional and name == "pro_materialization")
        probes.append(OriginProbe(name=name, url=url, required=is_required))
    return probes
