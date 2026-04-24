"""Materialization: Mapbox + optional Sentinel-2 (P1–P2)."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from pro_materialization_service.geospatial.asset_policy import (
    AnalysisProfile,
    SentinelFetchMode,
    TimBranch,
    validate_mode_matrix,
    validate_profile_mode_matrix,
)
from pro_materialization_service.geospatial.asset_version import (
    s2_asset_mapping_version,
    s2_band_asset_keys,
)
from pro_materialization_service.geospatial.bbox import square_bbox_wgs84
from pro_materialization_service.geospatial.mapbox_static import (
    fetch_mapbox_static_png,
    mapbox_access_token,
    mapbox_retry_count,
    mapbox_source_metadata,
    mapbox_timeout_seconds,
)
from pro_materialization_service.geospatial.s2_stac_load import apply_reflectance_scale, load_s2l2a_patch_np
from pro_materialization_service.geospatial.tim_export import rgb_mapbox_npz_from_png, s2l2a_npz_from_stack
from pro_materialization_service.geospatial.vlm_contracts import resolve_vlm_contract
from pro_materialization_service.geospatial.vlm_export import (
    cloud_mask_thumb_from_scl_png,
    false_color_swir_nir_red_png,
    png_sha256,
    resize_png_to_rgb_square,
)
from pro_materialization_service.models import (
    MaterializeRequest,
    MaterializeResult,
    TimPayload,
    VlmArtifact,
)

MAX_MAPBOX_SIDE = 1280
TIM_PATCH_HW = 224


_VLM_ROLES_NEED_S2: frozenset[str] = frozenset({"sentinel_fc", "cloud_mask_thumb"})


def _clamp_zoom(z: int) -> int:
    return max(0, min(18, z))


def _clamp_mapbox_size(n: int) -> int:
    return max(64, min(MAX_MAPBOX_SIDE, n))


def default_datetime_interval(days: int = 120) -> str:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return f"{start.isoformat()}/{end.isoformat()}"


def profile_materialization_policy(profile: AnalysisProfile) -> dict[str, Any]:
    days = {
        AnalysisProfile.WILDFIRE: 45,
        AnalysisProfile.OCEANSCOUT_SHIP_DETECTION: 21,
        AnalysisProfile.LAND_USE_CHANGE: 730,
        AnalysisProfile.FLOOD_PULSE: 30,
        AnalysisProfile.BRIEF_ONLY: 120,
    }[profile]
    return {
        "datetime_window_days": days,
        "mapbox_timeout_seconds": mapbox_timeout_seconds(),
        "mapbox_retry_count": mapbox_retry_count(),
    }


def compute_cache_key(req: MaterializeRequest) -> str:
    s2v = s2_asset_mapping_version()
    payload = {
        "bbox_half_km": req.bbox_half_km,
        "enable_tim": req.enable_tim,
        "latitude": round(req.latitude, 6),
        "longitude": round(req.longitude, 6),
        "mapbox_bearing": req.mapbox_bearing,
        "mapbox_pitch": req.mapbox_pitch,
        "mapbox_zoom": req.mapbox_zoom,
        "mapbox_size": req.mapbox_size,
        "max_cloud_cover": req.max_cloud_cover,
        "analysis_profile": req.analysis_profile,
        "retina": req.retina,
        "s2_asset_mapping_version": s2v,
        "sentinel_fetch_mode": req.sentinel_fetch_mode,
        "tim_branch": req.tim_branch,
        "vlm_contract_id": req.vlm_contract_id,
    }
    if req.datetime_interval:
        payload["datetime_interval"] = req.datetime_interval
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def materialize(req: MaterializeRequest, *, client: httpx.Client | None = None) -> MaterializeResult:
    """Dispatch by ``sentinel_fetch_mode`` (``plans/2026-04-12-...`` §5.3)."""
    mode = SentinelFetchMode(req.sentinel_fetch_mode)
    profile = AnalysisProfile(req.analysis_profile)
    profile_err = validate_profile_mode_matrix(
        analysis_profile=profile,
        sentinel_fetch_mode=mode,
        tim_branch=TimBranch(req.tim_branch),
        enable_tim=req.enable_tim,
    )
    if profile_err:
        raise ValueError(profile_err)
    if mode == SentinelFetchMode.MINIMAL_RGB:
        return materialize_rgb_mapbox(req, client=client)
    return materialize_spectral_paths(req, client=client)


def materialize_rgb_mapbox(
    req: MaterializeRequest,
    *,
    client: httpx.Client | None = None,
) -> MaterializeResult:
    """``MINIMAL_RGB``: Mapbox pin → VLM PNG; optional ``RGB`` TiM NPZ."""
    mode = SentinelFetchMode(req.sentinel_fetch_mode)
    tim_branch = TimBranch(req.tim_branch)
    err = validate_mode_matrix(sentinel_fetch_mode=mode, tim_branch=tim_branch, enable_tim=req.enable_tim)
    if err:
        raise ValueError(err)

    token = mapbox_access_token()
    if not token:
        raise ValueError("MAPBOX_TOKEN_MISSING")

    try:
        contract = resolve_vlm_contract(req.vlm_contract_id)
    except ValueError:
        raise ValueError("UNKNOWN_VLM_CONTRACT") from None

    if _VLM_ROLES_NEED_S2 & set(contract.roles):
        raise ValueError("VLM_CONTRACT_REQUIRES_SENTINEL_STACK")

    mid = str(uuid.uuid4())
    cache_key = compute_cache_key(req)
    zoom = float(_clamp_zoom(req.mapbox_zoom))
    mw = _clamp_mapbox_size(req.mapbox_size)
    mh = mw

    own_client = client is None
    hc = httpx.Client() if own_client else client
    assert hc is not None
    try:
        try:
            policy = profile_materialization_policy(AnalysisProfile(req.analysis_profile))
            raw_png, attribution = fetch_mapbox_static_png(
                hc,
                lon=req.longitude,
                lat=req.latitude,
                zoom=zoom,
                bearing=req.mapbox_bearing,
                pitch=req.mapbox_pitch,
                width=mw,
                height=mh,
                retina=req.retina,
                token=token,
                timeout_s=policy["mapbox_timeout_seconds"],
                retry_count=policy["mapbox_retry_count"],
            )
        except httpx.HTTPStatusError as e:
            raise ValueError(f"MAPBOX_HTTP_{e.response.status_code}") from e
        except httpx.RequestError:
            raise ValueError("MAPBOX_TRANSPORT_ERROR") from None
    finally:
        if own_client:
            hc.close()

    return _assemble_result(
        req=req,
        mid=mid,
        cache_key=cache_key,
        raw_mapbox_png=raw_png,
        mapbox_attribution=attribution,
        contract=contract,
        zoom=zoom,
        mw=mw,
        mh=mh,
        stac_meta=None,
        s2_stack_for_tim=None,
        scl_patch=None,
    )


def materialize_spectral_paths(
    req: MaterializeRequest,
    *,
    client: httpx.Client | None = None,
) -> MaterializeResult:
    """``TERRAMIND_SPECTRAL`` / ``FULL_STAC``: Mapbox + Sentinel-2 stack (P2)."""
    mode = SentinelFetchMode(req.sentinel_fetch_mode)
    tim_branch = TimBranch(req.tim_branch)
    err = validate_mode_matrix(sentinel_fetch_mode=mode, tim_branch=tim_branch, enable_tim=req.enable_tim)
    if err:
        raise ValueError(err)

    token = mapbox_access_token()
    if not token:
        raise ValueError("MAPBOX_TOKEN_MISSING")

    try:
        contract = resolve_vlm_contract(req.vlm_contract_id)
    except ValueError:
        raise ValueError("UNKNOWN_VLM_CONTRACT") from None

    mid = str(uuid.uuid4())
    cache_key = compute_cache_key(req)
    zoom = float(_clamp_zoom(req.mapbox_zoom))
    mw = _clamp_mapbox_size(req.mapbox_size)
    mh = mw

    own_client = client is None
    hc = httpx.Client() if own_client else client
    assert hc is not None
    try:
        try:
            policy = profile_materialization_policy(AnalysisProfile(req.analysis_profile))
            raw_png, attribution = fetch_mapbox_static_png(
                hc,
                lon=req.longitude,
                lat=req.latitude,
                zoom=zoom,
                bearing=req.mapbox_bearing,
                pitch=req.mapbox_pitch,
                width=mw,
                height=mh,
                retina=req.retina,
                token=token,
                timeout_s=policy["mapbox_timeout_seconds"],
                retry_count=policy["mapbox_retry_count"],
            )
        except httpx.HTTPStatusError as e:
            raise ValueError(f"MAPBOX_HTTP_{e.response.status_code}") from e
        except httpx.RequestError:
            raise ValueError("MAPBOX_TRANSPORT_ERROR") from None
    finally:
        if own_client:
            hc.close()

    profile_policy = profile_materialization_policy(AnalysisProfile(req.analysis_profile))
    dt = (req.datetime_interval or "").strip() or default_datetime_interval(profile_policy["datetime_window_days"])
    include_scl = "cloud_mask_thumb" in contract.roles
    try:
        stack, stac_meta, scl_patch = load_s2l2a_patch_np(
            lat=req.latitude,
            lon=req.longitude,
            datetime_range=dt,
            stac_url=req.stac_url.strip(),
            collection=req.collection_id.strip(),
            half_km=float(req.bbox_half_km),
            patch_hw=TIM_PATCH_HW,
            max_cloud=float(req.max_cloud_cover),
            asset_keys=s2_band_asset_keys(),
            max_items=20,
            include_scl=include_scl,
        )
    except ImportError as e:
        raise ValueError("S2_DEPENDENCIES_MISSING") from e
    except RuntimeError as e:
        msg = str(e).lower()
        if "no stac items" in msg:
            raise ValueError("STAC_NO_ITEMS") from e
        if (
            "missing asset" in msg
            or "missing scl" in msg
            or "scl geographic" in msg
            or "smaller than patch" in msg
            or "does not intersect" in msg
        ):
            raise ValueError("S2L2A_INCOMPLETE") from e
        raise ValueError("S2L2A_INCOMPLETE") from e
    except ValueError as e:
        if "12 asset keys" in str(e):
            raise ValueError("S2L2A_INCOMPLETE") from e
        raise

    stack = apply_reflectance_scale(stack, {})

    return _assemble_result(
        req=req,
        mid=mid,
        cache_key=cache_key,
        raw_mapbox_png=raw_png,
        mapbox_attribution=attribution,
        contract=contract,
        zoom=zoom,
        mw=mw,
        mh=mh,
        stac_meta=stac_meta,
        s2_stack_for_tim=stack,
        scl_patch=scl_patch,
    )


def _assemble_result(
    *,
    req: MaterializeRequest,
    mid: str,
    cache_key: str,
    raw_mapbox_png: bytes,
    mapbox_attribution: str,
    contract: Any,
    zoom: float,
    mw: int,
    mh: int,
    stac_meta: dict[str, Any] | None,
    s2_stack_for_tim: Any | None,
    scl_patch: Any | None,
) -> MaterializeResult:
    vlm_png = resize_png_to_rgb_square(raw_mapbox_png, contract.width, contract.height)
    west, south, east, north = square_bbox_wgs84(req.latitude, req.longitude, req.bbox_half_km)

    artifacts: list[VlmArtifact] = []
    for role in contract.roles:
        if role == "mapbox_rgb":
            digest = png_sha256(vlm_png)
            b64 = base64.standard_b64encode(vlm_png).decode("ascii")
            artifacts.append(
                VlmArtifact(
                    role=role,
                    sha256=digest,
                    mime="image/png",
                    width=contract.width,
                    height=contract.height,
                    inline_base64=b64,
                ),
            )
        elif role == "sentinel_fc":
            if s2_stack_for_tim is None:
                raise ValueError("VLM_ROLE_SENTINEL_FC_WITHOUT_STACK")
            fc_png = false_color_swir_nir_red_png(
                s2_stack_for_tim,
                contract.width,
                contract.height,
            )
            d_fc = png_sha256(fc_png)
            b64_fc = base64.standard_b64encode(fc_png).decode("ascii")
            artifacts.append(
                VlmArtifact(
                    role=role,
                    sha256=d_fc,
                    mime="image/png",
                    width=contract.width,
                    height=contract.height,
                    inline_base64=b64_fc,
                ),
            )
        elif role == "cloud_mask_thumb":
            if scl_patch is None:
                raise ValueError("VLM_ROLE_CLOUD_MASK_WITHOUT_SCL")
            cm_png = cloud_mask_thumb_from_scl_png(scl_patch, contract.width, contract.height)
            d_cm = png_sha256(cm_png)
            b64_cm = base64.standard_b64encode(cm_png).decode("ascii")
            artifacts.append(
                VlmArtifact(
                    role=role,
                    sha256=d_cm,
                    mime="image/png",
                    width=contract.width,
                    height=contract.height,
                    inline_base64=b64_cm,
                ),
            )
        else:
            raise ValueError(f"UNSUPPORTED_VLM_ROLE_{role}")

    tim_branch = TimBranch(req.tim_branch)
    tim_payload: TimPayload | None = None
    if req.enable_tim:
        if tim_branch == TimBranch.S2L2A_FULL:
            if s2_stack_for_tim is None:
                raise ValueError("S2L2A_INCOMPLETE")
            npz_bytes = s2l2a_npz_from_stack(s2_stack_for_tim)
            tim_payload = TimPayload(
                branch=tim_branch.value,
                npz_base64=base64.standard_b64encode(npz_bytes).decode("ascii"),
                modalities_keys=["S2L2A"],
            )
        else:
            npz_bytes = rgb_mapbox_npz_from_png(vlm_png)
            tim_payload = TimPayload(
                branch=tim_branch.value,
                npz_base64=base64.standard_b64encode(npz_bytes).decode("ascii"),
                modalities_keys=["RGB"],
            )

    manifest: dict[str, Any] = {
        "materialization_id": mid,
        "vlm_contract_id": req.vlm_contract_id,
        "vlm_roles": list(contract.roles),
        "tim_branch": req.tim_branch,
        "sentinel_fetch_mode": req.sentinel_fetch_mode,
        "mapbox_center_mode": "user_pin",
        "mapbox_attribution": mapbox_attribution,
        "mapbox_source": mapbox_source_metadata(),
        "profile_policy": profile_materialization_policy(AnalysisProfile(req.analysis_profile)),
        "bbox_wgs84": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_zoom": zoom,
        "mapbox_size_fetch": {"width": mw, "height": mh},
        "vlm_canvas": {"width": contract.width, "height": contract.height},
        "s2_asset_mapping_version": s2_asset_mapping_version(),
        "tim_patch_hw": TIM_PATCH_HW,
    }
    if "sentinel_fc" in contract.roles:
        manifest["vlm_false_color"] = {
            "bands_rgb_order": ("swir22", "nir", "red"),
            "stretch": "per_band_percentile_2_98",
        }
    if "cloud_mask_thumb" in contract.roles and stac_meta:
        sk = stac_meta.get("scl_asset_key")
        if sk:
            manifest["vlm_cloud_mask"] = {"source": "SCL", "scl_asset_key": sk, "resample": "nearest"}
    if stac_meta:
        manifest["stac"] = {
            "item_id": stac_meta.get("stac_item_id"),
            "datetime": stac_meta.get("stac_datetime"),
            "eo_cloud_cover": stac_meta.get("eo_cloud_cover"),
            "band_asset_keys": stac_meta.get("band_asset_keys"),
        }

    return MaterializeResult(
        materialization_id=mid,
        cache_key=cache_key,
        vlm_artifacts=artifacts,
        tim_payload=tim_payload,
        run_manifest=manifest,
        errors=[],
        warnings=[],
    )
