from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from nutonic_server.settings import Settings


def issue_session_token(settings: Settings) -> tuple[str, int]:
    """Anonymous device/session JWT (rules/05). Returns (token, expires_in_seconds)."""
    now = datetime.now(tz=UTC)
    exp = now + timedelta(seconds=settings.jwt_ttl_seconds)
    session_id = str(uuid.uuid4())
    payload: dict[str, object] = {
        "session_id": session_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "nutonic_session",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, settings.jwt_ttl_seconds


def decode_bearer_token(settings: Settings, token: str) -> dict[str, object]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def issue_round_ticket(settings: Settings, round_id: str, session_id: str) -> tuple[str, int]:
    """Short-lived JWT bound to a ranked round + session (IMP-090)."""
    now = datetime.now(tz=UTC)
    ttl = settings.ranked_round_ttl_seconds
    exp = now + timedelta(seconds=ttl)
    jti = str(uuid.uuid4())
    payload: dict[str, object] = {
        "typ": "nutonic_ranked_round",
        "round_id": round_id,
        "session_id": session_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, ttl


def decode_round_ticket(settings: Settings, token: str) -> dict[str, object]:
    """Decode and validate ``exp`` / signature (PyJWT defaults — expired tickets raise ``ExpiredSignatureError``)."""
    data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if data.get("typ") != "nutonic_ranked_round":
        raise jwt.InvalidTokenError("not a ranked round ticket")
    return data
