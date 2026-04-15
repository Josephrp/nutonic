from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from nutonic_server.bundles import resolve_bundle_bytes
from nutonic_server.inference_client import InferenceClient, InferenceClientConfig
import nutonic_server.catalog as game_catalog
from nutonic_server.deps import (
    get_settings,
    require_guess_record_claims,
    require_post_leaderboard_claims,
    require_pro_jobs_feature,
    require_ranked_read_public,
    require_ranked_session,
    require_session_jwt,
)
from nutonic_server.guess_telemetry_store import GuessTelemetryIn, create_guess_telemetry_store
from nutonic_server.haversine import haversine_km, score_from_distance_km
from nutonic_server.jwt_tokens import decode_round_ticket, issue_round_ticket, issue_session_token
from nutonic_server.leaderboard_store import LeaderboardRow, create_leaderboard_store
from nutonic_server.ranked_store import create_ranked_store
from nutonic_server.schemas import (
    CacheManifestOut,
    GuessRecordIn,
    GuessRecordOut,
    LeaderboardPostIn,
    LeaderboardRowOut,
    MapSummaryOut,
    ProJobCreateIn,
    ProJobCreateOut,
    ProJobStatusOut,
    RankedClueOut,
    RankedForfeitIn,
    RankedForfeitOut,
    RankedRoundStartIn,
    RankedRoundStartOut,
    RankedSubmitIn,
    RankedSubmitOut,
    TokenResponse,
)
from nutonic_server.settings import Settings, load_settings

settings = load_settings()
game_catalog.configure_catalog_from_manifest_path(settings.manifest_full_path)
_leaderboard_store = create_leaderboard_store(settings)
_ranked_store = create_ranked_store(settings.ranked_database_url)
_guess_telemetry_store = create_guess_telemetry_store(settings.guess_telemetry_database_url)
_pro_job_status: dict[str, str] = {}  # job_id -> "queued" | "completed"
_pro_job_materialization: dict[str, dict] = {}  # job_id -> summarized worker JSON (IMP-114)


def _summarize_materialize_worker_response(data: dict) -> dict:
    """Strip huge base64 from stored job payloads."""
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
        if k in rm
    }
    arts: list[dict] = []
    for a in data.get("vlm_artifacts") or []:
        if isinstance(a, dict):
            arts.append({k: a[k] for k in ("role", "sha256", "mime", "width", "height") if k in a})
    out: dict = {
        "materialization_id": data.get("materialization_id"),
        "cache_key": data.get("cache_key"),
        "run_manifest": slim_rm,
        "vlm_artifacts": arts,
    }
    tp = data.get("tim_payload")
    if isinstance(tp, dict):
        out["tim_payload"] = {
            "branch": tp.get("branch"),
            "modalities_keys": tp.get("modalities_keys"),
            "has_npz": bool(tp.get("npz_base64")),
        }
    return out

app = FastAPI(
    title="NU:TONIC Game Server",
    version="0.1.0",
    description="Thin orchestrator API (`/api/v1/*`). OpenAPI source: repo `docs/openapi.yaml`.",
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return flat JSON for feature_disabled (matches docs/openapi.yaml); otherwise FastAPI-style detail."""
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("error") == "feature_disabled":
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.get("/api/v1/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/config", tags=["config"])
def public_config(s: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    """Deployment capabilities for clients (IMP-001)."""
    return {
        "features": {
            "ranked": s.feature_ranked,
            "community_lb_get": s.feature_community_lb_get,
            "community_lb_post": s.feature_community_lb_post,
            "pro_jobs": s.feature_pro_jobs,
            "guesses_record": s.feature_guesses_record,
        }
    }


@app.post("/api/v1/auth/token", tags=["auth"], response_model=TokenResponse)
def issue_token(s: Annotated[Settings, Depends(get_settings)]) -> TokenResponse:
    """Anonymous session JWT (rules/05) for rate-limited / gated API use."""
    token, ttl = issue_session_token(s)
    return TokenResponse(access_token=token, expires_in=ttl)


@app.get("/api/v1/debug/session", tags=["debug"])
def debug_session(claims: Annotated[dict[str, object], Depends(require_session_jwt)]) -> dict[str, object]:
    """Gated sanity route (IMP-030): 401 without valid Bearer token."""
    return {"ok": True, "session_id": claims.get("session_id")}


@app.get("/api/v1/bundles/{bundle_id}", tags=["cache"])
def get_bundle(bundle_id: str) -> Response:
    """IMP-081: serve versioned still bytes (JPEG) for hydration without embedding multi‑MiB JSON."""
    resolved = resolve_bundle_bytes(bundle_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Unknown bundle_id")
    body, media = resolved
    return Response(content=body, media_type=media, headers={"Cache-Control": "public, max-age=3600"})


def _manifest_payload_and_etag(settings: Settings) -> tuple[dict[str, object], str]:
    expose = settings.expose_manifest_round_truth
    body = CacheManifestOut(
        content_version=game_catalog.CATALOG_MANIFEST_CONTENT_VERSION,
        engine_version=game_catalog.CATALOG_MANIFEST_ENGINE_VERSION,
        maps=list(game_catalog.PUBLISHED_MAPS),
        locations=list(game_catalog.MANIFEST_LOCATIONS) if expose else [],
        ai_guesses=list(game_catalog.MANIFEST_AI_GUESSES) if expose else [],
    )
    dumped = body.model_dump()
    canonical = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    etag = f'W/"{digest}"'
    return dumped, etag


def _if_none_match_includes_etag(if_none_match: str | None, etag: str) -> bool:
    """RFC 7232-style: comma-separated list, optional ``*`` wildcard (weak tag string equality)."""
    if not if_none_match:
        return False
    for part in if_none_match.split(","):
        candidate = part.strip()
        if candidate == "*":
            return True
        if candidate == etag:
            return True
    return False


@app.get("/api/v1/cache/manifest", tags=["cache"], response_model=None)
def get_cache_manifest(
    s: Annotated[Settings, Depends(get_settings)],
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Aggregate catalog + ``content_version`` for client hydration (IMP-080). Supports ``If-None-Match`` → 304."""
    dumped, etag = _manifest_payload_and_etag(s)
    if _if_none_match_includes_etag(if_none_match, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(content=dumped, headers={"ETag": etag})


@app.get("/api/v1/maps", tags=["maps"], response_model=list[MapSummaryOut])
def list_maps() -> list[MapSummaryOut]:
    """S1c minimal catalog (IMP-072): same rows as ``GET /api/v1/cache/manifest`` until DB-backed catalog lands."""
    return list(game_catalog.PUBLISHED_MAPS)


@app.get(
    "/api/v1/maps/{map_id}/leaderboard",
    tags=["leaderboard"],
    response_model=list[LeaderboardRowOut],
)
def get_leaderboard(
    map_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    tier: Annotated[
        str | None,
        Query(description="Use ``ranked`` for server-verified aggregate (same rows as ``…/leaderboard/ranked``)."),
    ] = None,
) -> list[LeaderboardRowOut]:
    """Per-map community rows, or ``tier=ranked`` for verified ranked aggregate (``docs/RANKED-MODE.md`` §4)."""
    t = (tier or "").strip().lower()
    if t == "ranked":
        if not settings.feature_ranked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "feature_disabled", "feature": "ranked"},
            )
        rows = _ranked_store.list_ranked_leaderboard(map_id.strip())
        return [LeaderboardRowOut.model_validate(r.__dict__) for r in rows]
    if not settings.feature_community_lb_get:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "community_lb_get"},
        )
    rows = _leaderboard_store.list_rows(map_id)
    return [LeaderboardRowOut.model_validate(r.__dict__) for r in rows]


@app.post(
    "/api/v1/maps/{map_id}/leaderboard",
    tags=["leaderboard"],
    response_model=LeaderboardRowOut,
)
def post_leaderboard_row(
    map_id: str,
    body: LeaderboardPostIn,
    claims: Annotated[dict[str, object], Depends(require_post_leaderboard_claims)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> LeaderboardRowOut:
    """Dev / lab community row (JWT required). Non-authoritative for ranked verification (`rules/05`)."""
    handle = body.display_handle.strip()[:64] or "ANON"
    role = body.player_role.strip().upper()[:32] or "HUMAN"
    row = LeaderboardRow(
        display_handle=handle,
        player_role=role,
        score_points=body.score_points,
        distance_km=body.distance_km,
    )
    key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    stored = _leaderboard_store.append_row(map_id, row, idempotency_key=key)
    _ = claims
    return LeaderboardRowOut.model_validate(stored.__dict__)


@app.get(
    "/api/v1/maps/{map_id}/leaderboard/ranked",
    tags=["leaderboard", "ranked"],
    response_model=list[LeaderboardRowOut],
)
def get_ranked_verified_leaderboard(
    map_id: str,
    _: Annotated[None, Depends(require_ranked_read_public)],
) -> list[LeaderboardRowOut]:
    """Server-verified ranked scores only (``docs/RANKED-MODE.md`` §4); separate from community GET."""
    rows = _ranked_store.list_ranked_leaderboard(map_id.strip())
    return [LeaderboardRowOut.model_validate(r.__dict__) for r in rows]


@app.post(
    "/api/v1/maps/{map_id}/guesses/record",
    tags=["telemetry"],
    response_model=GuessRecordOut,
)
def post_guess_record(
    map_id: str,
    body: GuessRecordIn,
    claims: Annotated[dict[str, object], Depends(require_guess_record_claims)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GuessRecordOut:
    """Non-authoritative guess audit trail (`rules/05`, `docs/GAME-ENGINE.md` §12.3)."""
    if _guess_telemetry_store is None:
        raise HTTPException(status_code=503, detail="Guess telemetry store not configured")
    sid = str(claims.get("session_id") or "")
    row = GuessTelemetryIn(
        map_id=map_id,
        round_instance_id=body.round_instance_id.strip()[:512],
        location_id=body.location_id.strip()[:256],
        guess_lat=body.guess_lat,
        guess_lon=body.guess_lon,
        client_distance_km=body.client_distance_km,
        ruleset_version=body.ruleset_version.strip()[:128] if body.ruleset_version else None,
        session_id=sid or None,
    )
    key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    rid = _guess_telemetry_store.record(row, idempotency_key=key)
    return GuessRecordOut(id=rid, recorded=True)


@app.post("/api/v1/ranked/rounds/start", tags=["ranked"], response_model=RankedRoundStartOut)
def ranked_round_start(
    body: RankedRoundStartIn,
    claims: Annotated[dict[str, object], Depends(require_ranked_session)],
    s: Annotated[Settings, Depends(get_settings)],
) -> RankedRoundStartOut:
    """Server-held secret round for ranked play (IMP-090)."""
    now_ts = int(datetime.now(tz=UTC).timestamp())
    _ranked_store.prune_stale_open_rounds(
        now_epoch=now_ts,
        max_age_seconds=s.ranked_stale_open_round_max_age_seconds,
    )
    loc = game_catalog.manifest_location_for_map(body.map_id.strip())
    if loc is None:
        raise HTTPException(status_code=404, detail="Unknown map_id for ranked catalog")
    session_id = str(claims.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=401, detail="session_id missing in token")
    rid = _ranked_store.create_round(
        map_id=loc.map_id,
        location_id=loc.location_id,
        truth_lat=float(loc.truth_lat),
        truth_lon=float(loc.truth_lon),
        session_id=session_id,
    )
    ticket, ttl = issue_round_ticket(s, rid, session_id)
    clue = RankedClueOut(
        map_id=loc.map_id,
        location_id=loc.location_id,
        still_bundle_id=loc.still_bundle_id,
        still_bundled_resource=loc.still_bundled_resource,
        useful_hints=loc.useful_hints,
        streetview_hint_pack=loc.streetview_hint_pack,
        streetview_assist_narrative=loc.streetview_assist_narrative,
        satellite_caption_sidecar=loc.satellite_caption_sidecar,
        play_budget_ms=loc.play_budget_ms,
        ai_marker_phase_enabled=loc.ai_marker_phase_enabled,
    )
    return RankedRoundStartOut(round_id=rid, round_ticket=ticket, expires_in=ttl, clue=clue)


@app.post(
    "/api/v1/ranked/rounds/{round_id}/forfeit-ranked-integrity",
    tags=["ranked"],
    response_model=RankedForfeitOut,
)
def ranked_forfeit_integrity(
    round_id: str,
    body: RankedForfeitIn,
    claims: Annotated[dict[str, object], Depends(require_ranked_session)],
) -> RankedForfeitOut:
    """Invalidate verified ranked participation before submit (IMP-091). ``reason`` is audit-only for now."""
    session_id = str(claims.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=401, detail="session_id missing in token")
    _ = body.reason  # reserved for future audit columns
    outcome = _ranked_store.forfeit_round(round_id, session_id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Unknown round_id")
    if outcome == "forbidden":
        raise HTTPException(status_code=403, detail="Session does not own this round")
    if outcome == "not_open":
        raise HTTPException(status_code=409, detail="Round not open for forfeit")
    return RankedForfeitOut()


@app.post(
    "/api/v1/ranked/rounds/{round_id}/submit",
    tags=["ranked"],
    response_model=RankedSubmitOut,
)
def ranked_round_submit(
    round_id: str,
    body: RankedSubmitIn,
    claims: Annotated[dict[str, object], Depends(require_ranked_session)],
    s: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RankedSubmitOut:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required for ranked submit")
    try:
        tclaims = decode_round_ticket(s, body.round_ticket.strip())
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Invalid round_ticket") from e
    if str(tclaims.get("round_id")) != round_id:
        raise HTTPException(status_code=400, detail="round_ticket does not match round_id")
    session_claim = str(claims.get("session_id") or "")
    if str(tclaims.get("session_id")) != session_claim:
        raise HTTPException(status_code=403, detail="round_ticket session mismatch")
    row = _ranked_store.get_round(round_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown round_id")
    if row.status == "forfeited":
        raise HTTPException(status_code=409, detail="Round forfeited")
    key = idempotency_key.strip()
    cached = _ranked_store.get_submit_if_exists(round_id, key)
    if cached is not None:
        d0, s0 = cached
        return RankedSubmitOut(distance_km=d0, score_points=s0, verified=True)
    if row.status != "open":
        raise HTTPException(status_code=409, detail="Round already closed")
    dist = haversine_km(body.guess_lat, body.guess_lon, row.truth_lat, row.truth_lon)
    score = score_from_distance_km(dist)
    d_out, s_out, inserted = _ranked_store.submit_idempotent_result(
        round_id,
        key,
        dist,
        score,
    )
    if inserted:
        _ranked_store.mark_submitted(round_id)
        _ranked_store.append_verified_leaderboard(
            map_id=row.map_id,
            round_id=round_id,
            session_id=session_claim,
            score_points=s_out,
            distance_km=d_out,
        )
    return RankedSubmitOut(distance_km=d_out, score_points=s_out, verified=True)


@app.post("/api/v1/pro/jobs", tags=["pro"], response_model=ProJobCreateOut)
def pro_create_job(
    body: ProJobCreateIn,
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> ProJobCreateOut:
    """PRO control plane: health probes (IMP-092) + optional ``POST …/internal/v1/materialize`` (IMP-114)."""
    jid = uuid.uuid4().hex
    _pro_job_status[jid] = "queued"
    _ = claims
    origins = [
        o
        for o in (
            s.inference_worker_base_url.strip(),
            s.pro_materialization_service_url.strip(),
        )
        if o
    ]
    pro_url = s.pro_materialization_service_url.strip()
    inference_ok: bool | None = None
    materialization_ok: bool | None = None
    materialization_id: str | None = None
    cache_key: str | None = None
    materialization_error: str | None = None
    if pro_url:
        materialization_ok = False
    if origins:
        try:
            hmac_secret = s.inference_hmac_secret.strip() or None
            ic_cfg = InferenceClientConfig(hmac_secret=hmac_secret)
            with InferenceClient(config=ic_cfg) as ic:
                inference_ok = all(ic.probe_health_origin(o) for o in origins)
                if pro_url and inference_ok:
                    base = pro_url.rstrip("/")
                    try:
                        mreq = {
                            "latitude": body.center_lat,
                            "longitude": body.center_lon,
                            "bbox_half_km": body.bbox_half_km,
                            "mapbox_zoom": body.mapbox_zoom,
                            "enable_tim": body.enable_tim,
                            "tim_branch": body.tim_branch,
                            "vlm_contract_id": body.vlm_contract_id,
                            "sentinel_fetch_mode": body.sentinel_fetch_mode,
                        }
                        if body.datetime_interval:
                            mreq["datetime_interval"] = body.datetime_interval
                        mat = ic.post_json(
                            f"{base}/internal/v1/materialize",
                            json_body=mreq,
                            read_timeout_s=120.0,
                        )
                        materialization_ok = True
                        materialization_id = str(mat.get("materialization_id") or "") or None
                        cache_key = str(mat.get("cache_key") or "") or None
                        _pro_job_materialization[jid] = _summarize_materialize_worker_response(mat)
                    except Exception as e:
                        materialization_ok = False
                        materialization_error = str(e)[:500]
                        _pro_job_materialization[jid] = {"error": materialization_error}
                elif pro_url and inference_ok is False:
                    materialization_ok = False
                    materialization_error = "inference_health_probe_failed"
                    _pro_job_materialization[jid] = {"error": materialization_error}
        except Exception:
            inference_ok = False
            if pro_url:
                materialization_ok = False
                materialization_error = "inference_client_error"
                _pro_job_materialization[jid] = {"error": materialization_error}
    return ProJobCreateOut(
        job_id=jid,
        status="queued",
        inference_upstream_ok=inference_ok,
        materialization_ok=materialization_ok,
        materialization_id=materialization_id,
        cache_key=cache_key,
        materialization_error=materialization_error,
    )


@app.get("/api/v1/pro/jobs/{job_id}", tags=["pro"], response_model=ProJobStatusOut)
def pro_job_status(
    job_id: str,
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    __: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> ProJobStatusOut:
    st = _pro_job_status.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    detail = _pro_job_materialization.get(job_id)
    mid = None if not detail or "error" in detail else detail.get("materialization_id")
    ck = None if not detail or "error" in detail else detail.get("cache_key")
    if st == "queued":
        _pro_job_status[job_id] = "completed"
        return ProJobStatusOut(
            job_id=job_id,
            status="queued",
            bundle_download_url=None,
            materialization_id=mid if isinstance(mid, str) else None,
            cache_key=ck if isinstance(ck, str) else None,
            materialization_summary=detail,
        )
    return ProJobStatusOut(
        job_id=job_id,
        status="completed",
        bundle_download_url=None,
        materialization_id=mid if isinstance(mid, str) else None,
        cache_key=ck if isinstance(ck, str) else None,
        materialization_summary=detail,
    )


def _maybe_mount_gradio(app_: FastAPI, s: Settings) -> None:
    if not s.enable_ops_gradio:
        return
    try:
        import gradio as gr  # type: ignore[import-untyped]
    except ImportError:
        return

    def _demo_rows(map_id: str = "demo") -> list[list[object]]:
        rows = _leaderboard_store.list_rows(map_id)
        return [[r.display_handle, r.player_role, r.score_points, r.distance_km] for r in rows]

    try:
        with gr.Blocks(title="NU:TONIC /ops") as blocks:
            gr.Markdown("# NU:TONIC operator leaderboard (read-only)")
            tbl = gr.Dataframe(headers=["handle", "role", "score", "distance_km"], label="demo map")
            btn = gr.Button("Refresh demo rows")
            btn.click(fn=_demo_rows, inputs=[], outputs=tbl)

        m = getattr(gr, "mount_gradio_app", None)
        if callable(m):
            m(app_, blocks, path="/ops")
    except Exception:
        return


_maybe_mount_gradio(app, settings)

_origins = settings.cors_origin_list()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
