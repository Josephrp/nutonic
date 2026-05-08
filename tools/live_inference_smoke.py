#!/usr/bin/env python3
"""
Live smoke client for deployed NU:TONIC HF Spaces.

Runs lightweight checks against:
- Game server (NuTonic/nutonic-game-server)
- LFM-VL hint service (Tonic/nutonic-lfm-vl-streetview)
- Street View pano service (Tonic/nutonic-streetview-pano)
- LFM-VL satellite caption service (Tonic/nutonic-lfm-vl-satellite)
- TerraMind TiM Space (Tonic/nutonic-terramind-tim)
- PRO materialization (NuTonic/nutonic-pro-materialization)

Defaults are derived from Space repo IDs, but you can override URLs with env vars:
- NUTONIC_GAME_SERVER_URL
- NUTONIC_LFM_VL_HINT_URL
- NUTONIC_STREETVIEW_PANO_URL
- NUTONIC_LFM_VL_SATELLITE_URL
- NUTONIC_TERRAMIND_TIM_URL
- NUTONIC_PRO_MATERIALIZATION_URL
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install httpx first: pip install httpx") from exc

from nutonic_hmac import nutonic_hmac_headers_from_env


REPO_ROOT = Path(__file__).resolve().parents[1]
_TIM_SRC = REPO_ROOT / "inference" / "terramind_tim_local" / "src"
if str(_TIM_SRC) not in sys.path:
    sys.path.insert(0, str(_TIM_SRC))
from nutonic_terramind_tim_local.tim_defaults import DEFAULT_TIM_MODEL_ID
PRESET_CHOICES = (
    "full",
    "lfm-deploy",
    "streetview-deploy",
    "satellite-deploy",
    "terramind-deploy",
    "game-deploy",
    "pro-deploy",
    "pro-readiness",
)


def _preset_services(preset: str) -> set[str]:
    if preset == "lfm-deploy":
        return {"lfm"}
    if preset == "streetview-deploy":
        return {"streetview"}
    if preset == "satellite-deploy":
        return {"satellite"}
    if preset == "terramind-deploy":
        return {"tim"}
    if preset == "game-deploy":
        return {"game"}
    if preset == "pro-deploy":
        return {"pro"}
    if preset == "pro-readiness":
        return {"lfm", "streetview", "satellite", "tim", "pro", "game"}
    return {"lfm", "streetview", "satellite", "tim", "pro", "game"}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if os.environ.get("NUTONIC_NO_DOTENV") == "1":
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()


def _space_url_from_repo_id(repo_id: str) -> str:
    slug = repo_id.strip().lower().replace("/", "-")
    return f"https://{slug}.hf.space"


def _tiny_png_base64() -> str:
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )


def _env_url(url_key: str, repo_key: str, default_repo_id: str) -> str:
    direct = (os.environ.get(url_key) or "").strip()
    if direct:
        return direct.rstrip("/")
    repo_id = (os.environ.get(repo_key) or default_repo_id).strip()
    return _space_url_from_repo_id(repo_id).rstrip("/")


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    http_status: int | None = None


def _ok(name: str, detail: str, http_status: int | None = None) -> CheckResult:
    return CheckResult(name=name, status="ok", detail=detail, http_status=http_status)


def _fail(name: str, detail: str, http_status: int | None = None) -> CheckResult:
    return CheckResult(name=name, status="fail", detail=detail, http_status=http_status)


def _skip(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="skip", detail=detail, http_status=None)


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    name: str,
    expected_statuses: tuple[int, ...] = (200,),
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    sign_with_env_hmac: bool = False,
) -> tuple[CheckResult, dict[str, Any] | list[Any] | str | None]:
    req_headers = dict(headers or {})
    content: bytes | None = None
    if json_body is not None:
        content = json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    if sign_with_env_hmac:
        signed = nutonic_hmac_headers_from_env(method, url, body=content or b"")
        req_headers.update(signed)

    try:
        response = client.request(method, url, content=content, headers=req_headers)
    except httpx.HTTPError as exc:
        return _fail(name, f"{type(exc).__name__}: {exc}"), None

    payload: dict[str, Any] | list[Any] | str | None
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:300]

    if response.status_code in expected_statuses:
        return _ok(name, f"{method} {url}", http_status=response.status_code), payload

    detail = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=True)[:300]
    return _fail(name, f"{method} {url} -> {response.status_code}: {detail}", response.status_code), payload


def _response_detail_code(payload: dict[str, Any] | list[Any] | str | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code is not None else None
    return None


def _post_pro_materialize_with_optional_build_wait(
    client: httpx.Client,
    *,
    mat_url: str,
    json_body: dict[str, Any],
    max_attempts: int,
    interval_sec: float,
) -> tuple[CheckResult, dict[str, Any] | list[Any] | str | None]:
    """
    HF Spaces apply uploaded Dockerfiles asynchronously; smoke may hit the previous image until
    the new build finishes. Retry only on 503 ``S2_DEPENDENCIES_MISSING`` (old image / build pending).
    """
    for attempt in range(max(1, max_attempts)):
        r, payload = _request_json(
            client,
            "POST",
            mat_url,
            name="pro.materialize",
            sign_with_env_hmac=True,
            json_body=json_body,
        )
        if r.status == "ok":
            return r, payload
        if (
            r.http_status == 503
            and _response_detail_code(payload) == "S2_DEPENDENCIES_MISSING"
            and attempt + 1 < max_attempts
        ):
            time.sleep(interval_sec)
            continue
        return r, payload
    raise RuntimeError("pro.materialize retry loop exited without return")  # pragma: no cover


def _extract_gradio_event_id(payload: dict[str, Any] | list[Any] | str | None) -> str:
    if isinstance(payload, dict):
        for k in ("event_id", "id", "hash", "session_hash"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                return v
        data = payload.get("data")
        if isinstance(data, dict):
            for k in ("event_id", "id"):
                v = data.get(k)
                if isinstance(v, str) and v:
                    return v
    if isinstance(payload, str):
        s = payload.strip()
        if s and s[0] != "{":
            return s
    return ""


def _request_gradio_named_endpoint(
    client: httpx.Client,
    *,
    base_url: str,
    api_name: str,
    name: str,
    req_payload: dict[str, Any],
) -> CheckResult:
    base = base_url.rstrip("/")
    submit_url = f"{base}/gradio_api/call/v2/{api_name}"
    submit_result, submit_payload = _request_json(
        client,
        "POST",
        submit_url,
        name=f"{name}.submit",
        json_body={"req": req_payload},
    )
    if submit_result.status != "ok":
        return _fail(name, f"Gradio fallback submit failed: {submit_result.detail}", submit_result.http_status)

    event_id = _extract_gradio_event_id(submit_payload)
    if not event_id:
        return _fail(name, "Gradio fallback missing event id in submit response.")

    result_url = f"{base}/gradio_api/call/{api_name}/{event_id}"
    try:
        response = client.get(result_url)
    except httpx.HTTPError as exc:
        return _fail(name, f"Gradio fallback poll failed: {type(exc).__name__}: {exc}")
    if response.status_code != 200:
        body = response.text[:300]
        return _fail(name, f"Gradio fallback poll failed: GET {result_url} -> {response.status_code}: {body}")
    body = response.text
    lowered = body.lower()
    if "event: error" in lowered or "traceback" in lowered:
        return _fail(name, f"Gradio fallback inference error from {result_url}: {body[:300]}")
    return _ok(name, f"POST {base}/gradio_api/call/v2/{api_name} (fallback)", http_status=200)


def _request_satellite_health(client: httpx.Client, *, base_url: str) -> CheckResult:
    health_url = f"{base_url.rstrip('/')}/health"
    r, _ = _request_json(client, "GET", health_url, name="satellite.health")
    if r.status == "ok":
        return r
    if r.http_status not in (404, 405):
        return r

    # Gradio-only startup mode may not expose `/health`; accept Gradio API info as liveness.
    info_url = f"{base_url.rstrip('/')}/gradio_api/info"
    info_result, payload = _request_json(client, "GET", info_url, name="satellite.health.gradio_info")
    if info_result.status != "ok":
        return _fail(
            "satellite.health",
            f"Neither /health nor /gradio_api/info is available: {info_result.detail}",
            info_result.http_status,
        )
    if isinstance(payload, dict) and "named_endpoints" in payload:
        return _ok("satellite.health", f"GET {info_url} (fallback)", http_status=info_result.http_status)
    return _fail("satellite.health", f"{info_url} returned unexpected payload shape.")


def _print_results(results: list[CheckResult], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": r.name,
                        "status": r.status,
                        "http_status": r.http_status,
                        "detail": r.detail,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
        return

    for r in results:
        hs = f" (http {r.http_status})" if r.http_status is not None else ""
        print(f"[{r.status.upper():4}] {r.name}{hs} - {r.detail}")


def _results_payload(
    results: list[CheckResult],
    *,
    preset: str,
    strict: bool,
    timeout: float,
    urls: dict[str, str],
) -> dict[str, Any]:
    fail_count = sum(1 for r in results if r.status == "fail")
    ok_count = sum(1 for r in results if r.status == "ok")
    skip_count = sum(1 for r in results if r.status == "skip")
    return {
        "meta": {
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "preset": preset,
            "strict": strict,
            "timeout_seconds": timeout,
            "urls": urls,
        },
        "summary": {
            "ok": ok_count,
            "fail": fail_count,
            "skip": skip_count,
            "total": len(results),
        },
        "results": [
            {
                "name": r.name,
                "status": r.status,
                "http_status": r.http_status,
                "detail": r.detail,
            }
            for r in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description="Smoke test deployed NU:TONIC HF services.")
    p.add_argument(
        "--preset",
        choices=PRESET_CHOICES,
        default="full",
        help=(
            "Check bundle to run. "
            "Use deploy presets in CI, or pro-readiness for cross-service PRO smoke."
        ),
    )
    p.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds (default: 20).")
    p.add_argument(
        "--run-pro-materialize",
        action="store_true",
        help="POST /internal/v1/materialize on PRO service (uses MAPBOX + optional HMAC headers).",
    )
    p.add_argument(
        "--run-pro-job",
        action="store_true",
        help="POST /api/v1/pro/jobs on game server (requires FEATURE_PRO_JOBS=true).",
    )
    p.add_argument(
        "--run-lfm-narrative",
        action="store_true",
        help="POST /v1/narrative/fuse on LFM service (can be slow on model backends).",
    )
    p.add_argument(
        "--run-terramind-export",
        action="store_true",
        help="POST /v1/tim/export on TerraMind Space (can be slow/expensive).",
    )
    p.add_argument("--lat", type=float, default=37.7749, help="Latitude for PRO materialize/job checks.")
    p.add_argument("--lon", type=float, default=-122.4194, help="Longitude for PRO materialize/job checks.")
    p.add_argument(
        "--pro-materialize-max-attempts",
        type=int,
        default=6,
        help=(
            "POST /internal/v1/materialize: max attempts on 503 S2_DEPENDENCIES_MISSING only "
            "(fallback when Hub build wait is not used). Default 6."
        ),
    )
    p.add_argument(
        "--pro-materialize-wait-interval",
        type=float,
        default=8.0,
        help="Seconds between those retries (default: 8).",
    )
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    p.add_argument(
        "--json-report-path",
        default="",
        help="Optional path to write a JSON report payload.",
    )
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any check fails.")
    args = p.parse_args(argv)
    services = _preset_services(args.preset)

    run_lfm_narrative = bool(args.run_lfm_narrative)
    run_pro_materialize = bool(args.run_pro_materialize)
    run_pro_job = bool(args.run_pro_job)
    run_terramind_export = bool(args.run_terramind_export)

    if args.preset in ("pro-deploy", "pro-readiness"):
        run_pro_materialize = True
    if args.preset == "pro-readiness":
        run_pro_job = True

    urls = {
        "game_server": _env_url(
            "NUTONIC_GAME_SERVER_URL",
            "NUTONIC_GAME_SERVER_REPO_ID",
            "NuTonic/nutonic-game-server",
        ),
        "lfm_vl_hint": _env_url(
            "NUTONIC_LFM_VL_HINT_URL",
            "NUTONIC_LFM_VL_HINT_REPO_ID",
            "Tonic/nutonic-lfm-vl-streetview",
        ),
        "streetview_pano": _env_url(
            "NUTONIC_STREETVIEW_PANO_URL",
            "NUTONIC_STREETVIEW_PANO_REPO_ID",
            "Tonic/nutonic-streetview-pano",
        ),
        "lfm_vl_satellite": _env_url(
            "NUTONIC_LFM_VL_SATELLITE_URL",
            "NUTONIC_LFM_VL_SATELLITE_REPO_ID",
            "Tonic/nutonic-lfm-vl-satellite",
        ),
        "terramind_tim": _env_url(
            "NUTONIC_TERRAMIND_TIM_URL",
            "NUTONIC_TERRAMIND_TIM_REPO_ID",
            "Tonic/nutonic-terramind-tim",
        ),
        "pro_materialization": (
            (os.environ.get("NUTONIC_PRO_MATERIALIZATION_URL") or "").strip().rstrip("/")
            or (os.environ.get("NUTONIC_PRO_MATERIALIZATION_SERVICE_URL") or "").strip().rstrip("/")
            or _env_url(
                "NUTONIC_PRO_MATERIALIZATION_URL",
                "NUTONIC_PRO_MATERIALIZATION_REPO_ID",
                "NuTonic/nutonic-pro-materialization",
            )
        ),
    }

    results: list[CheckResult] = []
    with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
        # LFM-VL hint
        if "lfm" in services:
            r, _ = _request_json(client, "GET", f"{urls['lfm_vl_hint']}/health", name="lfm.health")
            results.append(r)
            if run_lfm_narrative:
                r, _ = _request_json(
                    client,
                    "POST",
                    f"{urls['lfm_vl_hint']}/v1/narrative/fuse",
                    name="lfm.narrative_fuse",
                    json_body={
                        "captions": [
                            {"viewpoint_id": "v1", "text": "Road with dry hills and sparse trees."},
                            {"viewpoint_id": "v2", "text": "Low-density suburban edge near a bay."},
                        ],
                        "mission_flavor": "neutral",
                    },
                )
                results.append(r)
            else:
                results.append(_skip("lfm.narrative_fuse", "Skipped (use --run-lfm-narrative)."))

        # Street View pano
        if "streetview" in services:
            streetview_health_url = f"{urls['streetview_pano']}/health"
            r, _ = _request_json(
                client,
                "GET",
                streetview_health_url,
                name="streetview.health",
                sign_with_env_hmac=True,
            )
            results.append(r)
            sample_url = f"{urls['streetview_pano']}/api/v1/panos/sample"
            r, _ = _request_json(
                client,
                "POST",
                sample_url,
                name="streetview.panos_sample",
                sign_with_env_hmac=True,
                json_body={
                    "request_id": "hf_live_smoke",
                    "center": {"lat": args.lat, "lon": args.lon},
                    "count": 1,
                    "sampling_mode": "OMNI_SINGLE_PANO",
                    "image_width": 64,
                    "image_height": 64,
                },
            )
            results.append(r)

        # Satellite caption
        if "satellite" in services:
            results.append(_request_satellite_health(client, base_url=urls["lfm_vl_satellite"]))
            r, _ = _request_json(
                client,
                "POST",
                f"{urls['lfm_vl_satellite']}/v1/infer",
                name="satellite.infer",
                json_body={
                    "task": "caption",
                    "image_base64": _tiny_png_base64(),
                    "ranked_clue_safe": True,
                    "prompt_template_version": "satellite-v1",
                },
            )
            if r.status == "ok":
                results.append(r)
            elif r.http_status in (404, 405):
                results.append(
                    _request_gradio_named_endpoint(
                        client,
                        base_url=urls["lfm_vl_satellite"],
                        api_name="infer",
                        name="satellite.infer",
                        req_payload={
                            "task": "caption",
                            "image_base64": _tiny_png_base64(),
                            "ranked_clue_safe": True,
                            "prompt_template_version": "satellite-v1",
                        },
                    )
                )
            else:
                results.append(r)

        # TerraMind TiM
        if "tim" in services:
            r, _ = _request_json(client, "GET", f"{urls['terramind_tim']}/health", name="tim.health")
            results.append(r)
            if run_terramind_export:
                r, _ = _request_json(
                    client,
                    "POST",
                    f"{urls['terramind_tim']}/v1/tim/export",
                    name="tim.export",
                    json_body={
                        "config": {
                            "model_id": DEFAULT_TIM_MODEL_ID,
                            "pretrained": True,
                            "modalities": ["RGB"],
                            "tim_modalities": ["location"],
                            "merge_method": "mean",
                            "device": "cuda",
                            "inputs": {"mode": "random", "batch_size": 1},
                            "serialization": {
                                "tensor_sample_limit": 0,
                                "encoder_tensor_sample_limit": 0,
                                "include_encoder_trace": False,
                            },
                            "export": {
                                "map_id": "hf_live_smoke",
                                "location_id": "hf_live_smoke",
                                "include_ai_guess_row": True,
                            },
                        },
                    },
                )
                results.append(r)
            else:
                results.append(_skip("tim.export", "Skipped (use --run-terramind-export)."))

        # PRO materialization
        if "pro" in services:
            pro_health_url = f"{urls['pro_materialization']}/health"
            r, _ = _request_json(
                client,
                "GET",
                pro_health_url,
                name="pro.health",
                sign_with_env_hmac=True,
            )
            results.append(r)
            pro_healthz_url = f"{urls['pro_materialization']}/internal/v1/healthz"
            r, _ = _request_json(
                client,
                "GET",
                pro_healthz_url,
                name="pro.healthz",
                sign_with_env_hmac=True,
            )
            results.append(r)
            if run_pro_materialize:
                mat_url = f"{urls['pro_materialization']}/internal/v1/materialize"
                mat_body = {
                    "latitude": args.lat,
                    "longitude": args.lon,
                    "bbox_half_km": 5.0,
                    "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
                    "vlm_contract_id": "nutonic.pro.vlm.v1_512_s2_only",
                    "enable_tim": False,
                    "tim_branch": "RGB_mapbox",
                    "mapbox_zoom": 12,
                    "mapbox_size": 256,
                    "retina": False,
                }
                r, _ = _post_pro_materialize_with_optional_build_wait(
                    client,
                    mat_url=mat_url,
                    json_body=mat_body,
                    max_attempts=args.pro_materialize_max_attempts,
                    interval_sec=args.pro_materialize_wait_interval,
                )
                results.append(r)
            else:
                results.append(_skip("pro.materialize", "Skipped (use --run-pro-materialize)."))

        # Game server
        if "game" in services:
            r, _ = _request_json(client, "GET", f"{urls['game_server']}/api/v1/health", name="game.health")
            results.append(r)
            cfg_check, cfg_payload = _request_json(
                client,
                "GET",
                f"{urls['game_server']}/api/v1/config",
                name="game.config",
            )
            results.append(cfg_check)

            token: str | None = None
            tok_check, tok_payload = _request_json(
                client,
                "POST",
                f"{urls['game_server']}/api/v1/auth/token",
                name="game.auth_token",
            )
            results.append(tok_check)
            if tok_check.status == "ok" and isinstance(tok_payload, dict):
                token = str(tok_payload.get("access_token") or "") or None

            if run_pro_job:
                if not token:
                    results.append(_skip("game.pro_job_create", "Missing auth token from /api/v1/auth/token."))
                else:
                    pro_enabled = False
                    if isinstance(cfg_payload, dict):
                        features = cfg_payload.get("features")
                        if isinstance(features, dict):
                            pro_enabled = bool(features.get("pro_jobs"))
                    if not pro_enabled:
                        results.append(_skip("game.pro_job_create", "FEATURE_PRO_JOBS is disabled on server config."))
                    else:
                        headers = {"Authorization": f"Bearer {token}"}
                        readiness_check, readiness_payload = _request_json(
                            client,
                            "GET",
                            f"{urls['game_server']}/api/v1/pro/readiness",
                            name="game.pro_readiness",
                            headers=headers,
                        )
                        results.append(readiness_check)
                        if isinstance(readiness_payload, dict) and not readiness_payload.get("ready"):
                            reasons = readiness_payload.get("degraded_reasons")
                            results.append(
                                _fail(
                                    "game.pro_readiness.ready",
                                    f"PRO readiness is degraded: {reasons}",
                                    readiness_check.http_status,
                                )
                            )
                        else:
                            results.append(_ok("game.pro_readiness.ready", "PRO readiness reports ready."))

                        manifest_check, manifest_payload = _request_json(
                            client,
                            "GET",
                            f"{urls['game_server']}/api/v1/pro/vlm/model-manifest",
                            name="game.pro_vlm_model_manifest",
                            headers=headers,
                        )
                        results.append(manifest_check)
                        if isinstance(manifest_payload, dict):
                            missing = [
                                key
                                for key in ("model_bundle_id", "revision", "download_url", "sha256", "size_bytes", "contract_ids")
                                if not manifest_payload.get(key)
                            ]
                            if missing:
                                results.append(_fail("game.pro_vlm_model_manifest.fields", f"Missing fields: {missing}"))
                            else:
                                results.append(_ok("game.pro_vlm_model_manifest.fields", "Manifest has required fields."))

                        create_check, create_payload = _request_json(
                            client,
                            "POST",
                            f"{urls['game_server']}/api/v1/pro/jobs",
                            name="game.pro_job_create",
                            headers=headers,
                            json_body={
                                "center_lat": args.lat,
                                "center_lon": args.lon,
                                "bbox_half_km": 5.0,
                                "mapbox_zoom": 12,
                                "enable_tim": False,
                                "tim_branch": "RGB_mapbox",
                                "vlm_contract_id": "nutonic.pro.vlm.v1_512_s2_only",
                                "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
                            },
                        )
                        results.append(create_check)
                        if create_check.status == "ok" and isinstance(create_payload, dict):
                            jid = str(create_payload.get("job_id") or "")
                            if jid:
                                status_check, status_payload = _poll_pro_job(
                                    client,
                                    url=f"{urls['game_server']}/api/v1/pro/jobs/{jid}",
                                    headers=headers,
                                    timeout_seconds=max(30.0, args.timeout * 4),
                                )
                                results.append(status_check)
                                if isinstance(status_payload, dict) and status_payload.get("status") == "completed":
                                    payload = status_payload.get("on_device_payload")
                                    if isinstance(payload, dict) and payload.get("vlm_image_set"):
                                        results.append(_ok("game.pro_job_on_device_payload", "Completed job includes VLM image set."))
                                    else:
                                        results.append(
                                            _fail(
                                                "game.pro_job_on_device_payload",
                                                "Completed job is missing on_device_payload.vlm_image_set.",
                                            )
                                        )
                            else:
                                results.append(_fail("game.pro_job_status", "No job_id in create response."))
            else:
                results.append(_skip("game.pro_job_create", "Skipped (use --run-pro-job)."))

    payload = _results_payload(
        results,
        preset=args.preset,
        strict=bool(args.strict),
        timeout=args.timeout,
        urls=urls,
    )
    if args.json_report_path:
        report_path = Path(args.json_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_results(results, as_json=False)
    failed = any(r.status == "fail" for r in results)
    return 1 if (args.strict and failed) else 0


def _poll_pro_job(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[CheckResult, dict[str, Any] | list[Any] | str | None]:
    deadline = time.monotonic() + timeout_seconds
    last_result: CheckResult | None = None
    last_payload: dict[str, Any] | list[Any] | str | None = None
    while time.monotonic() < deadline:
        status_check, status_payload = _request_json(
            client,
            "GET",
            url,
            name="game.pro_job_status",
            headers=headers,
        )
        last_result = status_check
        last_payload = status_payload
        if status_check.status != "ok":
            return status_check, status_payload
        if isinstance(status_payload, dict) and status_payload.get("status") in {"completed", "failed", "cancelled"}:
            status = status_payload.get("status")
            if status == "completed":
                return _ok("game.pro_job_status", f"Job completed at {status_payload.get('progress_pct')}%.", status_check.http_status), status_payload
            return _fail("game.pro_job_status", f"Job ended with status {status}: {status_payload}", status_check.http_status), status_payload
        time.sleep(2.0)
    detail = "Timed out waiting for PRO job terminal status."
    if isinstance(last_payload, dict):
        detail += f" Last status: {last_payload.get('status')} {last_payload.get('progress_pct')}%."
    return _fail("game.pro_job_status", detail, last_result.http_status if last_result else None), last_payload


if __name__ == "__main__":
    raise SystemExit(main())
