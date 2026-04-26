"""
Configurable Google Earth Engine initialization.

Follows Google’s patterns for **service account keys** and **Application Default
Credentials** in the Earth Engine service account guide:
https://developers.google.com/earth-engine/guides/service_account#create-a-service-account

Resolution order (first match wins):

1. **Service account JSON** — any of ``--ee-service-account-key``, env
   ``EE_SERVICE_ACCOUNT_KEY_PATH``, or ``GOOGLE_APPLICATION_CREDENTIALS`` if it
   points to a file with ``"type": "service_account"``. Uses
   ``ee.ServiceAccountCredentials(client_email, key_path)`` then
   ``ee.Initialize(credentials=..., project=...)``. ``client_email`` is read from
   the JSON unless ``EE_SERVICE_ACCOUNT_EMAIL`` is set.

2. **Application Default Credentials** — ``google.auth.default(scopes=[Earth Engine])``
   then ``ee.Initialize(credentials=..., project=...)`` (for Compute Engine default
   SA, user ADC, etc.).

3. **Legacy** — ``ee.Initialize(project=...)`` or ``ee.Initialize()`` for
   interactive ``earthengine authenticate`` flows.

Project id: ``--ee-project`` > ``EE_PROJECT`` > ``EARTHENGINE_PROJECT`` > ``GCP_PROJECT``
> project returned with ADC (if any).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EE_SCOPE = "https://www.googleapis.com/auth/earthengine"


def _resolve_project(explicit: str | None) -> str | None:
    p = (explicit or "").strip()
    if p:
        return p
    for k in ("EE_PROJECT", "EARTHENGINE_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return None


def _service_account_key_paths(explicit_key: Path | str | None) -> list[Path]:
    """Ordered candidate JSON paths that may hold a Google **service account** key."""
    raw: list[Path] = []
    if explicit_key:
        raw.append(Path(explicit_key).expanduser())
    for envk in ("EE_SERVICE_ACCOUNT_KEY_PATH", "GOOGLE_APPLICATION_CREDENTIALS"):
        v = os.environ.get(envk, "").strip()
        if v:
            raw.append(Path(v).expanduser())
    out: list[Path] = []
    seen: set[str] = set()
    for p in raw:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def initialize_earth_engine(
    *,
    project: str | None = None,
    service_account_key: Path | str | None = None,
    service_account_email: str | None = None,
) -> dict[str, Any]:
    """
    Initialize the Earth Engine API. Safe to call more than once.

    Returns a small metadata dict (safe to log): ``mode``, ``project``, optional
    ``service_account``, ``key_file`` (basename only).
    """
    import ee

    try:
        ee.Number(1).getInfo()
        return {"mode": "already_initialized", "project": _resolve_project(project) or "(unknown)"}
    except Exception:  # noqa: BLE001
        pass

    proj = _resolve_project(project)
    email_override = (service_account_email or os.environ.get("EE_SERVICE_ACCOUNT_EMAIL", "")).strip() or None

    # --- 1) Service account + JSON key file (recommended when OAuth is blocked) ---
    for cand in _service_account_key_paths(service_account_key):
        rp = cand.resolve() if cand.exists() else cand
        if not rp.is_file():
            continue
        try:
            payload = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("type") != "service_account":
            continue
        email = email_override or payload.get("client_email")
        if not email:
            continue
        creds = ee.ServiceAccountCredentials(email, str(rp))
        if proj:
            ee.Initialize(credentials=creds, project=proj)
        else:
            ee.Initialize(credentials=creds)
        return {
            "mode": "service_account",
            "project": proj or "(default)",
            "service_account": email,
            "key_file": rp.name,
        }

    # --- 2) Application Default Credentials (GCE / gcloud / user ADC) ---
    try:
        import google.auth

        credentials, adc_project = google.auth.default(scopes=[EE_SCOPE])
        use_proj = proj or (adc_project if isinstance(adc_project, str) else None)
        if use_proj:
            ee.Initialize(credentials=credentials, project=use_proj)
        else:
            ee.Initialize(credentials=credentials)
        return {
            "mode": "application_default_credentials",
            "project": use_proj or str(adc_project),
        }
    except Exception:  # noqa: BLE001
        pass

    # --- 3) Legacy interactive / stored user credentials ---
    if proj:
        ee.Initialize(project=proj)
    else:
        ee.Initialize()
    return {"mode": "legacy_oauth_or_saved_user", "project": proj or "(default)"}
