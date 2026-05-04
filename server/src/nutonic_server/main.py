from __future__ import annotations

import hashlib
import io
import json
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, AsyncIterator

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from nutonic_server.bundles import resolve_bundle_bytes
import nutonic_server.catalog as game_catalog
from nutonic_server.deps import (
    get_pro_job_runner,
    get_pro_job_store,
    get_settings,
    require_guess_record_claims,
    require_post_leaderboard_claims,
    require_pro_jobs_feature,
    require_ranked_read_public,
    require_ranked_session,
    require_session_jwt,
    shutdown_pro_job_runners,
    start_pro_job_runner_for_settings,
)
from nutonic_server.guess_telemetry_store import GuessTelemetryIn, create_guess_telemetry_store
from nutonic_server.haversine import haversine_km, score_from_distance_km
from nutonic_server.inference_client import InferenceClient, InferenceClientConfig
from nutonic_server.jwt_tokens import decode_round_ticket, issue_round_ticket, issue_session_token
from nutonic_server.leaderboard_store import LeaderboardRow, create_leaderboard_store
from nutonic_server.pro_jobs_runner import ProJobRunner
from nutonic_server.pro_jobs_store import ProJobRecord, ProJobStore
from nutonic_server.production_analysis_prompt import (
    PRODUCTION_ANALYSIS_SYSTEM,
    build_production_tim_user_prompt,
    compact_tim_from_summary,
)
from nutonic_server.ranked_store import create_ranked_store
from nutonic_server.schemas import (
    CacheManifestOut,
    GuessRecordIn,
    GuessRecordOut,
    LeaderboardPostIn,
    LeaderboardRowOut,
    MapSummaryOut,
    ProArtifactRef,
    ProBriefSection,
    ProJobCancelOut,
    ProJobCreateIn,
    ProJobCreateOut,
    ProJobStatusOut,
    ProReadinessOut,
    ProVlmModelManifest,
    ProOnDevicePayload,
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


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = load_settings()
    if s.feature_pro_jobs:
        start_pro_job_runner_for_settings(s)
    try:
        yield
    finally:
        shutdown_pro_job_runners(grace_seconds=30.0)

app = FastAPI(
    title="NU:TONIC Game Server",
    version="0.1.0",
    description="Thin orchestrator API (`/api/v1/*`). OpenAPI source: repo `docs/openapi.yaml`.",
    lifespan=_lifespan,
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
        display_handle=body.display_handle.strip()[:64] if body.display_handle else None,
        score_points=body.score_points,
        player_role=body.player_role.strip()[:32] if body.player_role else None,
    )
    key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    return _guess_telemetry_store.record(row, idempotency_key=key)


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
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
    runner: Annotated[ProJobRunner, Depends(get_pro_job_runner)],
) -> ProJobCreateOut:
    """PRO control plane: persist and enqueue; worker I/O happens outside the request path."""
    session_id = _session_id_or_401(claims)
    record = store.create_job(
        session_id=session_id,
        analysis_profile=body.analysis_profile,
        request_params=body.model_dump(mode="json"),
    )
    runner.submit(record.job_id)
    return ProJobCreateOut(job_id=record.job_id, status="queued")


@app.get("/api/v1/pro/jobs", tags=["pro"], response_model=list[ProJobStatusOut])
def pro_list_jobs(
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    s: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[ProJobStatusOut]:
    session_id = _session_id_or_401(claims)
    statuses = _parse_status_filter(status_filter)
    return [_pro_status_out(row, s) for row in store.list_jobs(session_id=session_id, limit=limit, statuses=statuses)]


@app.get("/api/v1/pro/jobs/{job_id}", tags=["pro"], response_model=ProJobStatusOut)
def pro_job_status(
    job_id: str,
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    s: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> ProJobStatusOut:
    session_id = _session_id_or_401(claims)
    row = store.get_job(job_id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return _pro_status_out(row, s)


@app.get("/api/v1/pro/readiness", tags=["pro"], response_model=ProReadinessOut)
def pro_readiness(
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> ProReadinessOut:
    """Client-facing readiness contract: feature flag, worker probes, and local VLM bundle state."""
    hmac_secret = s.inference_hmac_secret.strip() or None
    materialization_url = s.pro_materialization_service_url.strip().rstrip("/")
    lfm_url = s.lfm_vl_hint_service_url.strip().rstrip("/")
    inference_url = s.inference_worker_base_url.strip().rstrip("/")
    materialization_healthy: bool | None = None
    lfm_healthy: bool | None = None
    inference_healthy: bool | None = None
    if s.feature_pro_jobs:
        cfg = InferenceClientConfig(hmac_secret=hmac_secret)
        with InferenceClient(config=cfg) as ic:
            if materialization_url:
                materialization_healthy = ic.probe_health_origin(materialization_url)
            if lfm_url:
                lfm_healthy = ic.probe_health_origin(lfm_url) or ic.probe_gradio_origin(lfm_url)
            if inference_url:
                inference_healthy = ic.probe_health_origin(inference_url)

    model_meta = _pro_vlm_model_manifest_or_none(s)
    degraded: list[str] = []
    if not s.feature_pro_jobs:
        degraded.append("feature_disabled")
    if not materialization_url:
        degraded.append("materialization_url_missing")
    elif materialization_healthy is False:
        degraded.append("materialization_unhealthy")
    if not lfm_url:
        degraded.append("lfm_brief_url_missing")
    elif lfm_healthy is False:
        degraded.append("lfm_brief_unhealthy")
    if inference_url and inference_healthy is False:
        degraded.append("inference_worker_unhealthy")
    if model_meta is None:
        degraded.append("vlm_model_unavailable")

    ready = (
        s.feature_pro_jobs
        and bool(materialization_url)
        and materialization_healthy is True
        and bool(lfm_url)
        and lfm_healthy is True
        and model_meta is not None
    )
    return ProReadinessOut(
        feature_enabled=s.feature_pro_jobs,
        ready=ready,
        materialization_configured=bool(materialization_url),
        materialization_healthy=materialization_healthy,
        lfm_brief_configured=bool(lfm_url),
        lfm_brief_healthy=lfm_healthy,
        inference_worker_configured=bool(inference_url),
        inference_worker_healthy=inference_healthy,
        vlm_model_configured=bool(s.pro_vlm_model_local_path.strip() or s.pro_vlm_model_download_url.strip()),
        vlm_model_available=model_meta is not None,
        vlm_model_bundle_id=model_meta.model_bundle_id if model_meta else None,
        degraded_reasons=degraded,
    )


@app.get("/api/v1/pro/vlm/model-manifest", tags=["pro"], response_model=ProVlmModelManifest)
def pro_vlm_model_manifest(
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    __: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> ProVlmModelManifest:
    manifest = _pro_vlm_model_manifest_or_none(s)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PRO VLM model manifest is not configured")
    return manifest


@app.get("/api/v1/pro/vlm/model-bundle", tags=["pro"], response_model=None)
def pro_vlm_model_bundle(
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    __: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> FileResponse:
    path = _local_model_path(s)
    if path is None:
        raise HTTPException(status_code=404, detail="PRO VLM model bundle is not baked into this server image")
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/v1/pro/jobs/{job_id}/cancel", tags=["pro"], response_model=ProJobCancelOut)
def pro_cancel_job(
    job_id: str,
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> ProJobCancelOut:
    session_id = _session_id_or_401(claims)
    outcome = store.request_cancel(job_id, session_id=session_id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if outcome in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail=f"Job already {outcome}")
    return ProJobCancelOut(status=outcome)


@app.get("/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}", tags=["pro"], response_model=None)
def pro_get_artifact(
    job_id: str,
    artifact_id: str,
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> FileResponse:
    session_id = _session_id_or_401(claims)
    row = store.get_job(job_id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    artifact = next((a for a in row.artifact_manifest or [] if a.get("artifact_id") == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Unknown artifact_id")
    path = _artifact_path(s.pro_artifact_root, job_id, artifact_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Artifact bytes are not available")
    return FileResponse(
        path,
        media_type=str(artifact.get("mime_type") or "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/v1/pro/jobs/{job_id}/bundle", tags=["pro"], response_model=None)
def pro_get_bundle(
    job_id: str,
    s: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> Response:
    """Return an atomic evidence bundle for a completed PRO job.

    The bundle is intentionally a zip containing a canonical JSON manifest plus
    artifact bytes. This is the local/server-hosted contract that can later map
    to object-storage signed URLs without changing the status field.
    """
    session_id = _session_id_or_401(claims)
    row = store.get_job(job_id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if row.status != "completed":
        raise HTTPException(status_code=409, detail=f"PRO job bundle is not available while status is {row.status}")
    body, digest = _build_pro_job_bundle(row, s)
    filename = f"nutonic-pro-{row.job_id[:12]}.zip"
    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{digest}"',
            "X-Nutonic-Bundle-SHA256": digest,
        },
    )


def _session_id_or_401(claims: dict[str, object]) -> str:
    session_id = str(claims.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=401, detail="session_id missing in token")
    return session_id


def _parse_status_filter(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    allowed = {"queued", "running", "completed", "failed", "cancelled"}
    statuses = {part.strip() for part in raw.split(",") if part.strip()}
    unknown = statuses - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown PRO job status filter: {', '.join(sorted(unknown))}")
    return statuses or None


def _pro_status_out(row: ProJobRecord, settings: Settings) -> ProJobStatusOut:
    artifacts = [_artifact_ref(row.job_id, a) for a in row.artifact_manifest or []]
    analysis_artifacts = [a for a in artifacts if a.profile != "brief_only"]
    brief_artifacts = [a for a in artifacts if a.profile == "brief_only" or a.kind == "brief"]
    status_reason = row.error_class or ("cancelled" if row.status == "cancelled" else None)
    materialization_summary = row.materialization_summary or None
    return ProJobStatusOut(
        job_id=row.job_id,
        status=row.status,
        status_reason=status_reason,
        error_class=row.error_class,
        error_detail=row.error_detail,
        progress_pct=row.progress_pct,
        profile=row.analysis_profile,
        analysis_profile=row.analysis_profile,
        started_at=row.started_at,
        finished_at=row.finished_at,
        artifacts=artifacts,
        analysis_artifacts=analysis_artifacts,
        brief_artifacts=brief_artifacts,
        scene_provenance=row.scene_provenance or None,
        on_device_payload=_on_device_payload(
            settings,
            materialization_summary,
            artifacts,
            analysis_artifacts,
            job_analysis_profile=row.analysis_profile,
        ),
        bundle_download_url=_pro_bundle_download_url(row),
        materialization_id=row.materialization_id,
        cache_key=row.cache_key,
        materialization_summary=materialization_summary,
    )


def _artifact_ref(job_id: str, raw: dict[str, object]) -> ProArtifactRef:
    artifact_id = str(raw.get("artifact_id") or "")
    download_url = f"/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}" if artifact_id else None
    return ProArtifactRef(
        artifact_id=artifact_id,
        kind=str(raw.get("kind") or "binary"),
        mime_type=str(raw.get("mime_type") or "application/octet-stream"),
        size_bytes=raw.get("size_bytes") if isinstance(raw.get("size_bytes"), int) else None,
        profile=str(raw.get("profile") or "") or None,
        contract_id=str(raw.get("contract_id") or "") or None,
        role=str(raw.get("role") or "") or None,
        category=str(raw.get("category") or "") or None,
        required_for_profile=bool(raw.get("required_for_profile")),
        download_url=download_url,
    )


def _pro_bundle_download_url(row: ProJobRecord) -> str | None:
    if row.status != "completed":
        return None
    return f"/api/v1/pro/jobs/{row.job_id}/bundle"


def _build_pro_job_bundle(row: ProJobRecord, settings: Settings) -> tuple[bytes, str]:
    artifact_entries: list[dict[str, object]] = []
    files: list[tuple[str, Path, bytes, dict[str, object]]] = []
    used_names: set[str] = set()

    for raw in row.artifact_manifest or []:
        artifact_id = str(raw.get("artifact_id") or "").strip()
        if not artifact_id:
            continue
        path = _artifact_path(settings.pro_artifact_root, row.job_id, artifact_id)
        if path is None:
            artifact_entries.append(
                _bundle_artifact_manifest_entry(raw, path_in_bundle=None, sha256=None, size_bytes=None, missing=True)
            )
            continue
        data = path.read_bytes()
        zip_name = _unique_bundle_path(artifact_id, path.suffix, used_names)
        files.append((zip_name, path, data, raw))
        artifact_entries.append(
            _bundle_artifact_manifest_entry(
                raw,
                path_in_bundle=zip_name,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                missing=False,
            )
        )

    status = _pro_status_out(row, settings).model_dump(mode="json")
    manifest = {
        "schema": "nutonic.pro.evidence_bundle.v1",
        "job_id": row.job_id,
        "status": row.status,
        "analysis_profile": row.analysis_profile,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "materialization_id": row.materialization_id,
        "cache_key": row.cache_key,
        "scene_provenance": row.scene_provenance,
        "materialization_summary": row.materialization_summary,
        "on_device_payload": status.get("on_device_payload"),
        "artifacts": artifact_entries,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("pro_bundle_manifest.json", manifest_bytes)
        for zip_name, _path, data, _raw in files:
            zf.writestr(zip_name, data)
    body = buf.getvalue()
    return body, hashlib.sha256(body).hexdigest()


def _bundle_artifact_manifest_entry(
    raw: dict[str, object],
    *,
    path_in_bundle: str | None,
    sha256: str | None,
    size_bytes: int | None,
    missing: bool,
) -> dict[str, object]:
    return {
        "artifact_id": str(raw.get("artifact_id") or ""),
        "kind": str(raw.get("kind") or "binary"),
        "mime_type": str(raw.get("mime_type") or "application/octet-stream"),
        "profile": str(raw.get("profile") or "") or None,
        "contract_id": str(raw.get("contract_id") or "") or None,
        "role": str(raw.get("role") or "") or None,
        "category": str(raw.get("category") or "") or None,
        "required_for_profile": bool(raw.get("required_for_profile")),
        "path": path_in_bundle,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "missing": missing,
    }


def _unique_bundle_path(artifact_id: str, suffix: str, used_names: set[str]) -> str:
    safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in artifact_id).strip("._")
    if not safe_id:
        safe_id = "artifact"
    ext = suffix if suffix.startswith(".") and len(suffix) <= 12 else ""
    candidate = f"artifacts/{safe_id}{ext}"
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    idx = 2
    while True:
        candidate = f"artifacts/{safe_id}-{idx}{ext}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        idx += 1


def _local_model_path(settings: Settings) -> Path | None:
    raw = settings.pro_vlm_model_local_path.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return None
    return path


def _pro_vlm_model_manifest_or_none(settings: Settings) -> ProVlmModelManifest | None:
    contract_ids = settings.pro_vlm_model_contract_id_list()
    local_path = _local_model_path(settings)
    download_url = settings.pro_vlm_model_download_url.strip()
    sha256 = settings.pro_vlm_model_sha256.strip().lower()
    size_bytes = settings.pro_vlm_model_size_bytes
    if local_path is not None:
        stat = local_path.stat()
        size_bytes = stat.st_size
        sha256 = _sha256_file(local_path)
        # Always serve baked bundles from this server; ignore any configured CDN/HF URL defaults.
        download_url = "/api/v1/pro/vlm/model-bundle"
    model_bundle_id = settings.pro_vlm_model_bundle_id.strip() or (f"nutonic.pro.vlm.{local_path.stem}" if local_path else "")
    revision = settings.pro_vlm_model_revision.strip() or (str(int(local_path.stat().st_mtime)) if local_path else "")
    if not (model_bundle_id and revision and download_url and sha256 and size_bytes > 0 and contract_ids):
        return None
    return ProVlmModelManifest(
        model_bundle_id=model_bundle_id,
        revision=revision,
        download_url=download_url,
        sha256=sha256,
        size_bytes=size_bytes,
        runtime=settings.pro_vlm_model_runtime.strip() or "leap",
        contract_ids=contract_ids,
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _on_device_payload(
    settings: Settings,
    materialization_summary: dict[str, object] | None,
    artifacts: list[ProArtifactRef],
    analysis_artifacts: list[ProArtifactRef],
    *,
    job_analysis_profile: str | None = None,
) -> ProOnDevicePayload | None:
    if not materialization_summary:
        return None
    brief = materialization_summary.get("brief_summary")
    sections: list[ProBriefSection] = []
    if isinstance(brief, dict):
        executive_summary = brief.get("executive_summary")
        if isinstance(executive_summary, str) and executive_summary.strip():
            sections.append(
                ProBriefSection(
                    title="Executive summary",
                    body=_bounded_text(executive_summary, 2000),
                    confidence=_brief_confidence(brief),
                )
            )
        key_findings = brief.get("key_findings")
        if isinstance(key_findings, list) and key_findings:
            body = "\n".join(f"- {str(item)[:300]}" for item in key_findings[:5])
            sections.append(ProBriefSection(title="Key findings", body=_bounded_text(body, 2000), confidence=_brief_confidence(brief)))
        recommended_actions = brief.get("recommended_actions")
        if isinstance(recommended_actions, list) and recommended_actions:
            body = "\n".join(f"- {str(item)[:300]}" for item in recommended_actions[:5])
            sections.append(ProBriefSection(title="Recommended actions", body=_bounded_text(body, 2000), confidence=None))
    image_set = _vlm_image_set(artifacts)
    if not sections and not analysis_artifacts and not image_set:
        return None
    conf_summary = _brief_confidence(brief) if isinstance(brief, dict) else None
    return ProOnDevicePayload(
        brief_sections=sections[:5],
        overlay_refs=analysis_artifacts[:4],
        confidence_summary=conf_summary,
        vlm_image_set=image_set,
        vlm_prompt_injection=_vlm_prompt_injection(
            materialization_summary,
            job_analysis_profile=job_analysis_profile,
        ),
        on_device_model_hint=settings.pro_vlm_model_runtime.strip() or "leap",
        model_bundle_id=_pro_vlm_model_bundle_id(settings),
    )


def _vlm_image_set(artifacts: list[ProArtifactRef]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for artifact in artifacts:
        if artifact.category != "vlm_image" and not artifact.mime_type.startswith("image/"):
            continue
        item: dict[str, object] = {
            "role": artifact.role or artifact.artifact_id,
            "artifact_id": artifact.artifact_id,
            "mime": artifact.mime_type,
        }
        if artifact.download_url:
            item["url"] = artifact.download_url
        out.append(item)
    return out[:4]


def _build_tim_context_dict_for_vlm(tim_summary: dict[str, Any] | None) -> dict[str, Any]:
    """TiM JSON shape aligned with ``terramind_assessment_sft.cap_tim_context`` / assessment prompts (no raw NPZ)."""
    ts = tim_summary if isinstance(tim_summary, dict) else {}
    out: dict[str, Any] = {}
    branch = ts.get("branch")
    if isinstance(branch, str) and branch.strip():
        out["branch"] = branch
    modalities = ts.get("modalities_keys")
    if isinstance(modalities, list):
        out["modalities_keys"] = modalities
    elif modalities is not None:
        out["modalities_keys"] = modalities
    if bool(ts.get("has_npz")):
        out["npz_base64"] = "<redacted>"
    mode = ts.get("mode")
    if isinstance(mode, str) and mode.strip():
        out["mode"] = mode
    tmo = ts.get("tim_modality_outputs")
    if isinstance(tmo, dict) and tmo:
        out["tim_modality_outputs"] = tmo
    return out if out else {"mode": ts.get("mode") if isinstance(ts.get("mode"), str) else "not_available"}


def _tim_context_block_text(tim_summary: dict[str, Any] | None) -> str:
    """Same prelude + ``indent=2`` JSON as ``terramind_assessment_sft.build_assessment_user_text`` TiM section."""
    tc = _build_tim_context_dict_for_vlm(tim_summary)
    body = json.dumps(tc, ensure_ascii=False, indent=2)
    return "- TerraMind / TiM context (capped JSON, model evidence only):\n" + body


def _vlm_prompt_injection(
    materialization_summary: dict[str, object] | None,
    *,
    job_analysis_profile: str | None = None,
) -> dict[str, object]:
    """On-device VLM: legacy ``tim_context_block`` plus SFT ``production_analysis`` user text (matches Patagonia eval)."""
    ms = materialization_summary if isinstance(materialization_summary, dict) else None
    run_manifest = ms.get("run_manifest") if ms else None
    tim_summary = ms.get("tim_summary") if ms else None
    ts_dict = tim_summary if isinstance(tim_summary, dict) else None
    mat_profile = ms.get("analysis_profile") if ms else None
    profile = (
        (job_analysis_profile or "").strip()
        or (str(mat_profile).strip() if isinstance(mat_profile, str) else "")
        or "brief_only"
    )
    tim_compact = compact_tim_from_summary(ts_dict)
    production_user = build_production_tim_user_prompt(analysis_profile=profile, tim_compact_json=tim_compact)
    return {
        "product": "NU:TONIC PRO",
        "vlm_prompt_style": "sft_production_analysis",
        "analysis_profile": profile,
        "production_analysis_system": PRODUCTION_ANALYSIS_SYSTEM,
        "production_tim_user_prompt": production_user,
        "tim_compact_json": tim_compact,
        "run_manifest": run_manifest if isinstance(run_manifest, dict) else {},
        "tim_context_block": _tim_context_block_text(ts_dict),
    }


def _pro_vlm_model_bundle_id(settings: Settings) -> str | None:
    explicit = settings.pro_vlm_model_bundle_id.strip()
    if explicit:
        return explicit
    local_path = _local_model_path(settings)
    return f"nutonic.pro.vlm.{local_path.stem}" if local_path else None


def _brief_confidence(brief: dict[str, object]) -> str | None:
    confidence = brief.get("confidence")
    if isinstance(confidence, str) and confidence.strip():
        return confidence.strip()[:64]
    return None


def _bounded_text(raw: str, max_len: int) -> str:
    text = raw.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _artifact_path(root: str, job_id: str, artifact_id: str) -> Path | None:
    job_dir = Path(root) / job_id
    if not job_dir.exists() or not job_dir.is_dir():
        return None
    for child in job_dir.iterdir():
        if child.is_file() and child.stem == artifact_id:
            return child
    return None


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
