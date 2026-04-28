"""FastAPI entry for PRO materialization (IMP-113 P0–P2)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import NoReturn

from fastapi import FastAPI, HTTPException

from pro_materialization_service import __version__
from pro_materialization_service.geospatial.asset_version import s2_asset_mapping_version
from pro_materialization_service.geospatial.pipeline import materialize
from pro_materialization_service.inference_hmac import hmac_secret, install_hmac_middleware, require_inbound_hmac
from pro_materialization_service.models import (
    MaterializeRequest,
    MaterializeResult,
    MaterializeStubIn,
    MaterializeStubOut,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if require_inbound_hmac() and not hmac_secret():
        raise RuntimeError(
            "NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC is enabled but "
            "NUTONIC_INFERENCE_HMAC_SECRET / INFERENCE_HMAC_SECRET is empty",
        )
    yield


app = FastAPI(title="NU:TONIC PRO materialization service", version=__version__, lifespan=_lifespan)
install_hmac_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "pro_materialization_service",
        "version": __version__,
    }


@app.get("/internal/v1/healthz")
def internal_healthz() -> dict[str, object]:
    """Control-plane probe (`plans/2026-04-12-...` §7.2)."""
    return {
        "ok": True,
        "version": __version__,
        "s2_asset_mapping_version": s2_asset_mapping_version(),
    }


def _map_stub_tim_branch(raw: str) -> str:
    u = raw.strip().lower().replace("-", "_")
    if u in ("s2l2a_full", "s2l2a"):
        return "S2L2A_full"
    return "RGB_mapbox"


def _materialize_http_errors(e: ValueError) -> NoReturn:
    code = str(e)
    if code.startswith("MAPBOX_HTTP_") or code == "MAPBOX_TRANSPORT_ERROR":
        raise HTTPException(status_code=502, detail={"code": code}) from e
    if code == "MAPBOX_TOKEN_MISSING":
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code == "UNKNOWN_VLM_CONTRACT":
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code == "VLM_CONTRACT_REQUIRES_SENTINEL_STACK":
        raise HTTPException(
            status_code=422,
            detail={
                "code": code,
                "message": "This vlm_contract_id includes sentinel_fc / cloud_mask_thumb; use TERRAMIND_SPECTRAL or FULL_STAC.",
            },
        ) from e
    if code in ("VLM_ROLE_SENTINEL_FC_WITHOUT_STACK", "VLM_ROLE_CLOUD_MASK_WITHOUT_SCL"):
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code.startswith("UNSUPPORTED_VLM_ROLE_"):
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code in (
        "TIM_BRANCH_REQUIRES_RGB_MAPBOX",
        "TIM_BRANCH_REQUIRES_S2L2A_FULL",
        "TIM_BRANCH_INVALID",
        "TIM_RGB_REQUIRES_MAPBOX_VLM_CONTRACT",
        "PROFILE_REQUIRES_TIM",
        "PROFILE_REQUIRES_SENTINEL_STACK",
        "PROFILE_REQUIRES_S2L2A_FULL",
    ):
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code in ("STAC_NO_ITEMS", "S2L2A_INCOMPLETE"):
        raise HTTPException(status_code=422, detail={"code": code}) from e
    if code == "S2_DEPENDENCIES_MISSING":
        raise HTTPException(
            status_code=503,
            detail={
                "code": code,
                "message": "Install optional deps: pip install nutonic-pro-materialization-service[s2]",
            },
        ) from e
    if code == "SENTINEL_PIPELINE_NOT_AVAILABLE":
        raise HTTPException(
            status_code=422,
            detail={
                "code": code,
                "message": "Deprecated error code — use a supported sentinel_fetch_mode.",
            },
        ) from e
    raise HTTPException(status_code=400, detail={"code": code}) from e


@app.post("/internal/v1/materialize", response_model=MaterializeResult)
def internal_materialize(body: MaterializeRequest) -> MaterializeResult:
    """
    Mapbox-centered materialization + optional Sentinel-2 (``MINIMAL_RGB`` / ``TERRAMIND_SPECTRAL`` / ``FULL_STAC``).
    """
    try:
        return materialize(body)
    except ValueError as e:
        _materialize_http_errors(e)


@app.post("/api/v1/materialize/stub", response_model=MaterializeStubOut)
def materialize_stub(body: MaterializeStubIn) -> MaterializeStubOut:
    """
    Back-compat alias: same as ``POST /internal/v1/materialize`` with defaults.

    Prefer ``/internal/v1/materialize`` for orchestration (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`).
    """
    req = MaterializeRequest(
        latitude=body.latitude,
        longitude=body.longitude,
        tim_branch=_map_stub_tim_branch(body.tim_input_branch),  # type: ignore[arg-type]
        sentinel_fetch_mode="MINIMAL_RGB",
        enable_tim=False,
    )
    try:
        out = materialize(req)
    except ValueError as e:
        _materialize_http_errors(e)
    roles = [a.role for a in out.vlm_artifacts]
    return MaterializeStubOut(
        materialization_id=out.materialization_id,
        latitude=body.latitude,
        longitude=body.longitude,
        tim_input_branch=body.tim_input_branch,
        cache_key=out.cache_key,
        vlm_roles=roles,
    )
