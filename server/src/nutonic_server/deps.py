from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nutonic_server.jwt_tokens import decode_bearer_token
from nutonic_server.hf_persistence import HfSqliteSync
from nutonic_server.pro_jobs_runner import ProJobRunner
from nutonic_server.pro_jobs_store import ProJobStore, create_pro_job_store
from nutonic_server.settings import Settings, load_settings
from nutonic_server.leaderboard_store import sqlite_file_path_from_url

_bearer = HTTPBearer(auto_error=False)
_pro_job_stores: dict[str, ProJobStore] = {}
_pro_job_runners: dict[str, ProJobRunner] = {}


def get_settings() -> Settings:
    return load_settings()


def get_pro_job_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProJobStore:
    return get_pro_job_store_for_settings(settings)


def get_pro_job_store_for_settings(settings: Settings) -> ProJobStore:
    if settings.pro_job_backend.strip().lower() != "sqlite":
        raise HTTPException(status_code=500, detail="Unsupported PRO job backend")
    url = settings.pro_job_database_url.strip()
    if url not in _pro_job_stores:
        sync_hook = None
        db_path = sqlite_file_path_from_url(url)
        if db_path is not None:
            hf = HfSqliteSync.from_settings(settings)
            if hf is not None:
                hf.bootstrap_sqlite_file(local_path=db_path, logical_name="pro_jobs")
                sync_hook = hf.make_write_sync_hook(local_path=db_path, logical_name="pro_jobs")
        _pro_job_stores[url] = create_pro_job_store(url, on_write=sync_hook)
    return _pro_job_stores[url]


def get_pro_job_runner(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ProJobStore, Depends(get_pro_job_store)],
) -> ProJobRunner:
    return get_pro_job_runner_for_settings(settings, store)


def get_pro_job_runner_for_settings(settings: Settings, store: ProJobStore) -> ProJobRunner:
    key = "|".join(
        (
            settings.pro_job_database_url.strip(),
            settings.pro_materialization_service_url.strip(),
            settings.lfm_vl_hint_service_url.strip(),
            settings.inference_worker_base_url.strip(),
            settings.pro_required_origins.strip(),
            settings.pro_optional_origins.strip(),
            settings.pro_artifact_root.strip(),
        )
    )
    if key not in _pro_job_runners:
        _pro_job_runners[key] = ProJobRunner(settings=settings, store=store)
    return _pro_job_runners[key]


def start_pro_job_runner_for_settings(settings: Settings) -> ProJobRunner:
    store = get_pro_job_store_for_settings(settings)
    runner = get_pro_job_runner_for_settings(settings, store)
    runner.start()
    return runner


def shutdown_pro_job_runners(*, grace_seconds: float = 30.0) -> None:
    for runner in list(_pro_job_runners.values()):
        runner.shutdown(grace_seconds=grace_seconds)


def require_community_lb_get(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """When `features.community_lb_get` is false, return 403 (product-flags v1)."""
    if not settings.feature_community_lb_get:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "community_lb_get"},
        )


def require_community_lb_post(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """When `features.community_lb_post` is false, return 403 (product-flags v1)."""
    if not settings.feature_community_lb_post:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "community_lb_post"},
        )


def require_session_jwt(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_bearer_token(settings, creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def require_post_leaderboard_claims(
    _: Annotated[None, Depends(require_community_lb_post)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> dict[str, object]:
    """Community leaderboard POST: feature gate runs before Bearer validation (403 before 401)."""
    return claims


def require_ranked_feature(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.feature_ranked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "ranked"},
        )


def require_pro_jobs_feature(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.feature_pro_jobs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "pro_jobs"},
        )


def require_guesses_record_feature(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.feature_guesses_record:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "guesses_record"},
        )


def require_ranked_session(
    _: Annotated[None, Depends(require_ranked_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> dict[str, object]:
    return claims


def require_ranked_read_public(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Read-only ranked surfaces (e.g. verified aggregate) without session JWT (`docs/RANKED-MODE.md` §4)."""
    if not settings.feature_ranked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "feature": "ranked"},
        )


def require_guess_record_claims(
    _: Annotated[None, Depends(require_guesses_record_feature)],
    claims: Annotated[dict[str, object], Depends(require_session_jwt)],
) -> dict[str, object]:
    return claims

