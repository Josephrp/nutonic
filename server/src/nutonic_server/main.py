from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, AsyncIterator

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
from nutonic_server.jwt_tokens import decode_round_ticket, issue_round_ticket, issue_session_token
from nutonic_server.leaderboard_store import LeaderboardRow, create_leaderboard_store
from nutonic_server.pro_jobs_runner import ProJobRunner
from nutonic_server.pro_jobs_store import ProJobRecord, ProJobStore
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
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[ProJobStatusOut]:
    session_id = _session_id_or_401(claims)
    statuses = _parse_status_filter(status_filter)
    return [_pro_status_out(row) for row in store.list_jobs(session_id=session_id, limit=limit, statuses=statuses)]


@app.get("/api/v1/pro/jobs/{job_id}", tags=["pro"], response_model=ProJobStatusOut)
def pro_job_status(
    job_id: str,
    _: Annotated[None, Depends(require_pro_jobs_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> ProJobStatusOut:
    session_id = _session_id_or_401(claims)
    row = store.get_job(job_id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return _pro_status_out(row)


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


def _pro_status_out(row: ProJobRecord) -> ProJobStatusOut:
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
        on_device_payload=_on_device_payload(materialization_summary, analysis_artifacts),
        bundle_download_url=None,
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
        download_url=download_url,
    )


def _on_device_payload(
    materialization_summary: dict[str, object] | None,
    analysis_artifacts: list[ProArtifactRef],
) -> ProOnDevicePayload | None:
    if not materialization_summary:
        return None
    brief = materialization_summary.get("brief_summary")
    if not isinstance(brief, dict):
        return None
    sections: list[ProBriefSection] = []
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
    if not sections and not analysis_artifacts:
        return None
    return ProOnDevicePayload(
        brief_sections=sections[:5],
        overlay_refs=analysis_artifacts[:4],
        confidence_summary=_brief_confidence(brief),
    )


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
