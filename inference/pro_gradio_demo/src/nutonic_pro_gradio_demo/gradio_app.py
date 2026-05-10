from __future__ import annotations

import time
from typing import Any

import gradio as gr
import httpx

from nutonic_pro_gradio_demo.client import NutonicServerClient
from nutonic_pro_gradio_demo.models import ProJobCreateIn, ProJobStatusOut
from nutonic_pro_gradio_demo.image_fetch import fetch_vlm_images
from nutonic_pro_gradio_demo.render import decode_image, draw_boxes
from nutonic_pro_gradio_demo.settings import get_settings
from nutonic_pro_gradio_demo.vlm_parse import parse_vlm_output
from nutonic_pro_gradio_demo.vlm_runtime import ensure_model_loaded, zerogpu_infer_caption_and_boxes

LEAFLET_JS = ""

def _new_client() -> NutonicServerClient:
    """
    Create a fresh client per Gradio invocation.

    This avoids cross-user/session token reuse: PRO artifacts are session-bound on the
    game server (`session_id` in JWT), so sharing a token across concurrent Space users
    can cause intermittent 401s when fetching artifacts for a job created by a different session.
    """
    return NutonicServerClient(get_settings())

ON_DEVICE_VLM_USER_INSTRUCTION_LINES = "\n".join(
    [
        "NU:TONIC PRO on-device vision — describe the provided EO image set using visible evidence.",
        (
            "You are a geospatial analyst specializing in satellite imagery interpretation. "
            "Analyze the provided Sentinel-2 satellite images and report findings grounded in visible evidence. "
            "Use [x1, y1, x2, y2] bounding boxes normalized to 0-1 relative to image dimensions."
        ),
        (
            "This is optical-only observation. Avoid certainty claims beyond visible evidence, "
            "and state confidence and limitations where appropriate."
        ),
        (
            "Return a concise caption followed by strict JSON with key `boxes`. "
            "Each box must be `{label,bbox,confidence}` with bbox normalized [x1,y1,x2,y2] in 0..1."
        ),
    ]
)


def _build_vlm_prompt(*, prompt_injection: dict[str, Any] | None = None) -> str:
    """
    Prompt aligned with `nutonic/shared/.../ProModelPromptContract.ON_DEVICE_VLM_USER_INSTRUCTION_LINES`.
    We append a compact context JSON block when present (server-supplied).
    """
    injection = prompt_injection or {}
    if not injection:
        return ON_DEVICE_VLM_USER_INSTRUCTION_LINES
    return ON_DEVICE_VLM_USER_INSTRUCTION_LINES + "\n\nCONTEXT_JSON:\n" + str(injection)


def _bbox_half_km_for_zoom(zoom: int) -> float:
    z = int(zoom)
    z = min(18, max(1, z))
    if z >= 16:
        return 0.5
    if z >= 15:
        return 1.0
    if z >= 14:
        return 2.0
    if z >= 13:
        return 3.0
    if z >= 12:
        return 5.0
    if z >= 11:
        return 8.0
    if z >= 10:
        return 12.0
    if z >= 9:
        return 20.0
    if z >= 8:
        return 35.0
    if z >= 7:
        return 60.0
    if z >= 6:
        return 100.0
    return 250.0


def _zoom_for_bbox_half_km(bbox_half_km: float) -> int:
    v = float(bbox_half_km)
    if v <= 0.5:
        return 16
    if v <= 1.0:
        return 15
    if v <= 2.0:
        return 14
    if v <= 3.0:
        return 13
    if v <= 5.0:
        return 12
    if v <= 8.0:
        return 11
    if v <= 12.0:
        return 10
    if v <= 20.0:
        return 9
    if v <= 35.0:
        return 8
    if v <= 60.0:
        return 7
    if v <= 100.0:
        return 6
    return 5


def _run_job(
    *,
    center_lat: float,
    center_lon: float,
    mapbox_zoom: int,
    analysis_profile: str,
    enable_tim: bool,
    tim_branch: str,
    sentinel_fetch_mode: str,
    vlm_contract_id: str,
    datetime_interval: str | None,
    scene_id_t0: str | None,
    scene_id_t1: str | None,
    scene_id_t2: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    bbox_half_km = _bbox_half_km_for_zoom(mapbox_zoom)
    client = _new_client()
    try:
        bearer = client.post_auth_token().access_token
        created = client.post_pro_job(
            ProJobCreateIn(
                center_lat=center_lat,
                center_lon=center_lon,
                bbox_half_km=bbox_half_km,
                mapbox_zoom=mapbox_zoom,
                analysis_profile=analysis_profile,  # type: ignore[arg-type]
                enable_tim=enable_tim,
                tim_branch=tim_branch,  # type: ignore[arg-type]
                sentinel_fetch_mode=sentinel_fetch_mode,  # type: ignore[arg-type]
                vlm_contract_id=vlm_contract_id,
                datetime_interval=datetime_interval or None,
                scene_id_t0=scene_id_t0 or None,
                scene_id_t1=scene_id_t1 or None,
                scene_id_t2=scene_id_t2 or None,
            )
        )
        job_id = created.job_id
        last: ProJobStatusOut | None = None
        started = time.time()
        while True:
            last = client.get_pro_job(job_id, bearer_token=bearer)
            if last.status in {"completed", "failed", "cancelled"}:
                break
            if time.time() - started > settings.poll_timeout_seconds:
                raise TimeoutError(f"Timed out polling PRO job {job_id}")
            time.sleep(max(0.2, settings.poll_interval_seconds))
        return last.model_dump(mode="json") if last else {"job_id": job_id, "status": "unknown"}
    except httpx.HTTPStatusError as e:
        resp = e.response
        return {
            "error": "upstream_http_error",
            "status_code": resp.status_code if resp is not None else None,
            "detail": str(e),
            "hint": "The upstream game server Space may be rate-limiting (429). Wait and retry, or reduce repeated clicks.",
        }
    finally:
        client.close()

def _run_full_pipeline(
    *,
    center_lat: float,
    center_lon: float,
    mapbox_zoom: int,
    analysis_profile: str,
    enable_tim: bool,
    tim_branch: str,
    sentinel_fetch_mode: str,
    vlm_contract_id: str,
    datetime_interval: str | None,
    scene_id_t0: str | None,
    scene_id_t1: str | None,
    scene_id_t2: str | None,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    settings = get_settings()
    bbox_half_km = _bbox_half_km_for_zoom(mapbox_zoom)
    client = _new_client()
    try:
        bearer = client.post_auth_token().access_token
        created = client.post_pro_job(
            ProJobCreateIn(
                center_lat=center_lat,
                center_lon=center_lon,
                bbox_half_km=bbox_half_km,
                mapbox_zoom=mapbox_zoom,
                analysis_profile=analysis_profile,  # type: ignore[arg-type]
                enable_tim=enable_tim,
                tim_branch=tim_branch,  # type: ignore[arg-type]
                sentinel_fetch_mode=sentinel_fetch_mode,  # type: ignore[arg-type]
                vlm_contract_id=vlm_contract_id,
                datetime_interval=datetime_interval or None,
                scene_id_t0=scene_id_t0 or None,
                scene_id_t1=scene_id_t1 or None,
                scene_id_t2=scene_id_t2 or None,
            )
        )
        job = client.poll_until_terminal(
            job_id=created.job_id,
            poll_interval_seconds=settings.poll_interval_seconds,
            poll_timeout_seconds=settings.poll_timeout_seconds,
            bearer_token=bearer,
        )
        if job.status != "completed":
            # Workaround: bypass orchestrator and call workers directly.
            if (
                settings.enable_direct_worker_fallback
                and job.error_class == "worker_unreachable"
                and job.status_reason == "worker_unreachable"
            ):
                return _run_via_direct_workers(
                    client=client,
                    center_lat=center_lat,
                    center_lon=center_lon,
                    bbox_half_km=bbox_half_km,
                    mapbox_zoom=mapbox_zoom,
                    analysis_profile=analysis_profile,
                    enable_tim=enable_tim,
                    tim_branch=tim_branch,
                    sentinel_fetch_mode=sentinel_fetch_mode,
                    vlm_contract_id=vlm_contract_id,
                    datetime_interval=datetime_interval,
                    scene_id_t0=scene_id_t0,
                    scene_id_t1=scene_id_t1,
                    scene_id_t2=scene_id_t2,
                )
            return job.model_dump(mode="json"), None, None, {"error": f"Job ended with status {job.status}"}

        images = fetch_vlm_images(client=client, job=job, bearer_token=bearer)
        if not images:
            return job.model_dump(mode="json"), None, None, {"error": "No vlm_image_set images found on job"}

        max_n = settings.vlm_max_images
        pils = [decode_image(fi.bytes).convert("RGB") for fi in images[:max_n]]
        # First image is used for bbox overlay (normalized coords match primary scene in practice).
        pil_primary = pils[0]

        prompt_injection = (job.on_device_payload.vlm_prompt_injection if job.on_device_payload else None) or {}
        prompt = _build_vlm_prompt(prompt_injection=prompt_injection)

        t0 = time.time()
        loaded = ensure_model_loaded(client=client, settings=settings)
        raw_text = zerogpu_infer_caption_and_boxes(loaded=loaded, prompt=prompt, image_rgb=pils)
        t1 = time.time()

        parsed = parse_vlm_output(
            raw_text=raw_text,
            model_bundle_id=loaded.manifest.model_bundle_id,
            revision=loaded.manifest.revision,
            source="hf_space_vlm",
        )
        annotated = draw_boxes(pil_primary, parsed.boxes)
        meta = {
            "inference_seconds": round(t1 - t0, 3),
            "model_bundle_id": loaded.manifest.model_bundle_id,
            "revision": loaded.manifest.revision,
            "vlm_image_count": len(pils),
            "vlm_image_roles": [fi.role for fi in images[:max_n]],
            "vlm_override_bundle_id": settings.vlm_override_bundle_id.strip() or None,
            "vlm_override_revision": settings.vlm_override_revision.strip() or None,
        }
        return job.model_dump(mode="json"), pil_primary, annotated, {"vlm_result": parsed.model_dump(mode="json"), "meta": meta}
    except httpx.HTTPStatusError as e:
        resp = e.response
        # The upstream game server can be degraded in two ways:
        # - 429: rate-limiting (often on /auth/token)
        # - 404 after POST 200: non-sticky routing / per-replica job state (job-id not found when polling)
        # In both cases, bypass orchestrator and call workers directly.
        if (
            settings.enable_direct_worker_fallback
            and resp is not None
            and resp.status_code in {404, 429, 502, 503, 504}
        ):
            return _run_via_direct_workers(
                client=client,
                center_lat=center_lat,
                center_lon=center_lon,
                bbox_half_km=bbox_half_km,
                mapbox_zoom=mapbox_zoom,
                analysis_profile=analysis_profile,
                enable_tim=enable_tim,
                tim_branch=tim_branch,
                sentinel_fetch_mode=sentinel_fetch_mode,
                vlm_contract_id=vlm_contract_id,
                datetime_interval=datetime_interval,
                scene_id_t0=scene_id_t0,
                scene_id_t1=scene_id_t1,
                scene_id_t2=scene_id_t2,
            )
        err = {
            "error": "upstream_http_error",
            "status_code": resp.status_code if resp is not None else None,
            "detail": str(e),
            "hint": "If this is 429, the upstream Space is rate-limiting. If this is 404 after job creation, the job API is non-sticky; the demo can bypass it via direct-worker mode.",
        }
        return {"error": err}, None, None, err
    finally:
        client.close()


def _run_via_direct_workers(
    *,
    client: NutonicServerClient,
    center_lat: float,
    center_lon: float,
    bbox_half_km: float,
    mapbox_zoom: int,
    analysis_profile: str,
    enable_tim: bool,
    tim_branch: str,
    sentinel_fetch_mode: str,
    vlm_contract_id: str,
    datetime_interval: str | None,
    scene_id_t0: str | None,
    scene_id_t1: str | None,
    scene_id_t2: str | None,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    settings = get_settings()
    mat_origin = settings.pro_materialization_origin
    # Best-effort health probe. If it fails, still attempt materialization — some Space
    # replicas / proxies can make health flaky while the POST path works fine.
    health_ok = client.probe_health_origin(mat_origin)

    # Call materialization directly. This is the same payload the orchestrator would send.
    try:
        mat = client.post_json_to_origin(
            origin=mat_origin,
            path="/internal/v1/materialize",
            json_body={
                "latitude": center_lat,
                "longitude": center_lon,
                "bbox_half_km": bbox_half_km,
                "datetime_interval": datetime_interval or None,
                "sentinel_fetch_mode": sentinel_fetch_mode,
                "analysis_profile": analysis_profile,
                "mapbox_zoom": mapbox_zoom,
                "vlm_contract_id": vlm_contract_id,
                "enable_tim": bool(enable_tim),
                "tim_branch": tim_branch,
                "scene_id_t0": scene_id_t0 or None,
                "scene_id_t1": scene_id_t1 or None,
                "scene_id_t2": scene_id_t2 or None,
            },
        )
    except httpx.HTTPStatusError as e:
        resp = e.response
        err = {
            "error": "direct_worker_materialize_failed",
            "worker": "pro_materialization",
            "origin": mat_origin,
            "health_ok": health_ok,
            "status_code": resp.status_code if resp is not None else None,
            "detail": str(e),
        }
        return {"error": err}, None, None, err

    artifacts = mat.get("vlm_artifacts") if isinstance(mat, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        err = {"error": "no_vlm_artifacts", "materialization_result": mat}
        return {"materialization": mat}, None, None, err

    import base64

    max_n = settings.vlm_max_images
    decoded_rows: list[bytes] = []
    roles: list[str | None] = []
    for a in artifacts:
        if not isinstance(a, dict) or not a.get("inline_base64"):
            continue
        decoded_rows.append(base64.b64decode(str(a["inline_base64"])))
        roles.append(a.get("role") if isinstance(a.get("role"), str) else None)
        if len(decoded_rows) >= max_n:
            break

    if not decoded_rows:
        err = {"error": "no_inline_base64", "materialization_result": mat}
        return {"materialization": mat}, None, None, err

    pils = [decode_image(b).convert("RGB") for b in decoded_rows]
    pil_primary = pils[0]

    prompt = _build_vlm_prompt(prompt_injection=None)
    t0 = time.time()
    loaded = ensure_model_loaded(client=client, settings=settings)
    raw_text = zerogpu_infer_caption_and_boxes(loaded=loaded, prompt=prompt, image_rgb=pils)
    t1 = time.time()
    parsed = parse_vlm_output(
        raw_text=raw_text,
        model_bundle_id=loaded.manifest.model_bundle_id,
        revision=loaded.manifest.revision,
        source="hf_space_vlm",
    )
    annotated = draw_boxes(pil_primary, parsed.boxes)
    meta = {
        "path": "direct_workers",
        "inference_seconds": round(t1 - t0, 3),
        "model_bundle_id": loaded.manifest.model_bundle_id,
        "revision": loaded.manifest.revision,
        "vlm_image_count": len(pils),
        "vlm_image_roles": roles[: len(pils)],
        "vlm_override_bundle_id": settings.vlm_override_bundle_id.strip() or None,
        "vlm_override_revision": settings.vlm_override_revision.strip() or None,
        "materialization_id": mat.get("materialization_id") if isinstance(mat, dict) else None,
        "cache_key": mat.get("cache_key") if isinstance(mat, dict) else None,
    }
    return {"materialization": mat}, pil_primary, annotated, {"vlm_result": parsed.model_dump(mode="json"), "meta": meta}


def build_demo() -> gr.Blocks:
    settings = get_settings()
    # Used by app.py (Gradio 6 moved js= from Blocks(...) to launch()).
    # Keep it as a local value and return it via a module constant below.
    leaflet_js = r"""
function() {
  // Load Leaflet (CSS + JS) dynamically (OSM tiles; no Mapbox).
  function loadCss(href) {
    return new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.onload = resolve;
      link.onerror = reject;
      document.head.appendChild(link);
    });
  }
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  async function ensureLeaflet() {
    if (window.L && window.L.map) return;
    await loadCss("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css");
    await loadScript("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
  }

  function setValue(elemId, value) {
    const el = document.getElementById(elemId);
    if (!el) return;
    // Works for Gradio inputs rendered as <input> or <textarea>.
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function init() {
    await ensureLeaflet();
    const mapDiv = document.getElementById("nutonic_map");
    if (!mapDiv) return;
    if (mapDiv.dataset.initialized === "1") return;
    mapDiv.dataset.initialized = "1";

    const defaultLat = 47.6062;
    const defaultLon = -122.3321;
    const defaultZoom = 9;

    const map = window.L.map("nutonic_map").setView([defaultLat, defaultLon], defaultZoom);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    let marker = window.L.marker([defaultLat, defaultLon]).addTo(map);

    function update(lat, lon) {
      setValue("nutonic_center_lat", lat.toFixed(6));
      setValue("nutonic_center_lon", lon.toFixed(6));
      if (marker) marker.setLatLng([lat, lon]);
    }

    map.on("click", function(e) {
      const lat = e.latlng.lat;
      const lon = e.latlng.lng;
      update(lat, lon);
    });

    // Bootstrap initial values.
    update(defaultLat, defaultLon);
  }

  // Defer until Gradio finished rendering.
  setTimeout(init, 50);
}
"""

    global LEAFLET_JS
    LEAFLET_JS = leaflet_js

    with gr.Blocks(title="NU:TONIC PRO (ZeroGPU demo)") as demo:
        if settings.require_server_origin and not settings.nutonic_server_origin.strip():
            gr.Markdown(
                "## Configuration required\n\n"
                "Set the Space variable `NUTONIC_SERVER_ORIGIN` to the game server base URL "
                "(must expose `/api/v1/pro/jobs` and `/api/v1/pro/vlm/model-manifest`)."
            )
            return demo
        hmac_state = "enabled" if (settings.inference_hmac_secret or "").strip() else "disabled"
        gr.Markdown(
            "## NU:TONIC PRO — ZeroGPU demo\n\n"
            "This Space submits a PRO job to the configured game server, polls it to completion, "
            "then runs the final VLM locally (Transformers) on ZeroGPU.\n\n"
            f"**Server origin:** `{settings.nutonic_server_origin or '(unset)'}`  \n"
            f"**Outbound HMAC signing:** `{hmac_state}`"
        )

        gr.Markdown("### Pick analysis center (interactive map)\nClick the map to set latitude/longitude.")
        gr.HTML(
            """
<div style="height: 360px; width: 100%; border-radius: 12px; overflow: hidden; border: 1px solid rgba(255,255,255,0.14);">
  <div id="nutonic_map" style="height: 360px; width: 100%;"></div>
</div>
""".strip()
        )

        with gr.Row():
            # These textboxes are updated by Leaflet JS via elem_id.
            center_lat = gr.Textbox(label="Center latitude", value="47.606200", elem_id="nutonic_center_lat")
            center_lon = gr.Textbox(label="Center longitude", value="-122.332100", elem_id="nutonic_center_lon")
            mapbox_zoom = gr.Slider(label="Zoom (maps to AOI radius)", minimum=1, maximum=18, step=1, value=12)

        bbox_preview = gr.Number(label="AOI radius km (derived from zoom)", value=_bbox_half_km_for_zoom(12), interactive=False)

        def _update_bbox(z: int) -> float:
            return _bbox_half_km_for_zoom(int(z))

        mapbox_zoom.change(fn=_update_bbox, inputs=mapbox_zoom, outputs=bbox_preview)

        with gr.Row():
            analysis_profile = gr.Dropdown(
                label="Analysis profile",
                choices=["brief_only", "wildfire", "oceanscout_ship_detection", "land_use_change", "flood_pulse"],
                value="brief_only",
            )
            enable_tim = gr.Checkbox(label="Enable TiM", value=False)
            tim_branch = gr.Dropdown(label="TiM branch", choices=["S2L2A_full", "RGB_mapbox"], value="S2L2A_full")

        with gr.Row():
            sentinel_fetch_mode = gr.Dropdown(
                label="Sentinel fetch mode",
                choices=["TERRAMIND_SPECTRAL", "FULL_STAC"],
                value="TERRAMIND_SPECTRAL",
            )
            vlm_contract_id = gr.Textbox(label="VLM contract id", value="nutonic.pro.vlm.v1_512_s2_only")

        with gr.Accordion("Advanced provenance pinning", open=False):
            datetime_interval = gr.Textbox(label="Datetime interval (optional)", value="")
            with gr.Row():
                scene_id_t0 = gr.Textbox(label="scene_id_t0 (optional)", value="")
                scene_id_t1 = gr.Textbox(label="scene_id_t1 (optional)", value="")
                scene_id_t2 = gr.Textbox(label="scene_id_t2 (optional)", value="")

        run_job = gr.Button("Run PRO job (upstream)", variant="primary")
        job_out = gr.JSON(label="PRO job status (completed job)")

        run_job.click(
            fn=lambda *args: _run_job(
                center_lat=args[0],
                center_lon=args[1],
                mapbox_zoom=args[2],
                analysis_profile=args[3],
                enable_tim=args[4],
                tim_branch=args[5],
                sentinel_fetch_mode=args[6],
                vlm_contract_id=args[7],
                datetime_interval=args[8],
                scene_id_t0=args[9],
                scene_id_t1=args[10],
                scene_id_t2=args[11],
            ),
            inputs=[
                center_lat,
                center_lon,
                mapbox_zoom,
                analysis_profile,
                enable_tim,
                tim_branch,
                sentinel_fetch_mode,
                vlm_contract_id,
                datetime_interval,
                scene_id_t0,
                scene_id_t1,
                scene_id_t2,
            ],
            outputs=job_out,
            api_name="run_pro_job",
        )

        gr.Markdown("## Full pipeline (upstream job + local VLM)")
        run_all = gr.Button("Run full pipeline", variant="primary")
        raw_img = gr.Image(label="Raw VLM image", type="pil")
        annotated_img = gr.Image(label="Annotated output", type="pil")
        final_json = gr.JSON(label="Final outputs (VLM result + meta)")

        run_all.click(
            fn=lambda *args: _run_full_pipeline(
                center_lat=args[0],
                center_lon=args[1],
                mapbox_zoom=args[2],
                analysis_profile=args[3],
                enable_tim=args[4],
                tim_branch=args[5],
                sentinel_fetch_mode=args[6],
                vlm_contract_id=args[7],
                datetime_interval=args[8],
                scene_id_t0=args[9],
                scene_id_t1=args[10],
                scene_id_t2=args[11],
            ),
            inputs=[
                center_lat,
                center_lon,
                mapbox_zoom,
                analysis_profile,
                enable_tim,
                tim_branch,
                sentinel_fetch_mode,
                vlm_contract_id,
                datetime_interval,
                scene_id_t0,
                scene_id_t1,
                scene_id_t2,
            ],
            outputs=[job_out, raw_img, annotated_img, final_json],
            api_name="run_full_pipeline",
        )
    return demo

