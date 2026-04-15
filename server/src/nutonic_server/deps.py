from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nutonic_server.jwt_tokens import decode_bearer_token
from nutonic_server.settings import Settings, load_settings

_bearer = HTTPBearer(auto_error=False)


def get_settings() -> Settings:
    return load_settings()


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

