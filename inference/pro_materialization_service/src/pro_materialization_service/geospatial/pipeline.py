"""Materialization: Sentinel-2 EO (+ optional TiM); Mapbox-backed VLM contracts are rejected."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from PIL import Image

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
    mapbox_retry_count,
    mapbox_source_metadata,
    mapbox_timeout_seconds,
)
from pro_materialization_service.geospatial.s2_stac_load import apply_reflectance_scale, load_s2l2a_patch_np
from pro_materialization_service.geospatial.tim_export import rgb_mapbox_npz_from_png, s2l2a_npz_from_stack
from pro_materialization_service.geospatial.vlm_contracts import VlmContract, resolve_vlm_contract
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


_TEMPORAL_PROFILES: frozenset[AnalysisProfile] = frozenset(
    {
        AnalysisProfile.WILDFIRE,
        AnalysisProfile.OCEANSCOUT_SHIP_DETECTION,
        AnalysisProfile.LAND_USE_CHANGE,
        AnalysisProfile.FLOOD_PULSE,
    },
)


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
    for key in ("scene_id_t0", "scene_id_t1", "scene_id_t2"):
        value = getattr(req, key, None)
        if value:
            payload[key] = value
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def temporal_scene_specs(
    req: MaterializeRequest,
    *,
    profile: AnalysisProfile,
    datetime_interval: str,
    window_days: int,
) -> list[tuple[str, str, str | None]]:
    if profile not in _TEMPORAL_PROFILES and not (req.scene_id_t0 or req.scene_id_t1 or req.scene_id_t2):
        return [("t1", datetime_interval, req.scene_id_t1)]
    specs = [
        ("t0", previous_datetime_interval(datetime_interval, window_days), req.scene_id_t0),
        ("t1", datetime_interval, req.scene_id_t1),
    ]
    if req.scene_id_t2:
        specs.append(("t2", datetime_interval, req.scene_id_t2))
    return specs


def previous_datetime_interval(datetime_interval: str, days: int) -> str:
    start, end = _parse_datetime_interval(datetime_interval)
    if start is None:
        return datetime_interval
    width = max(1, (end - start).days if end is not None else int(days))
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=width)
    return f"{prev_start.isoformat()}/{prev_end.isoformat()}"


def _parse_datetime_interval(datetime_interval: str) -> tuple[Any | None, Any | None]:
    raw_start, sep, raw_end = datetime_interval.partition("/")
    if not sep:
        return None, None
    return _parse_interval_date(raw_start), _parse_interval_date(raw_end)


def _parse_interval_date(value: str) -> Any | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def materialize(req: MaterializeRequest) -> MaterializeResult:
    """Dispatch by ``sentinel_fetch_mode`` (``plans/2026-04-12-...`` §5.3)."""
    mode = SentinelFetchMode(req.sentinel_fetch_mode)
    profile = AnalysisProfile(req.analysis_profile)
    tim_branch = TimBranch(req.tim_branch)
    profile_err = validate_profile_mode_matrix(
        analysis_profile=profile,
        sentinel_fetch_mode=mode,
        tim_branch=tim_branch,
        enable_tim=req.enable_tim,
    )
    if profile_err:
        raise ValueError(profile_err)
    mode_err = validate_mode_matrix(sentinel_fetch_mode=mode, tim_branch=tim_branch, enable_tim=req.enable_tim)
    if mode_err:
        raise ValueError(mode_err)
    try:
        contract = resolve_vlm_contract(req.vlm_contract_id)
    except ValueError:
        raise ValueError("UNKNOWN_VLM_CONTRACT") from None
    if "mapbox_rgb" in contract.roles:
        raise ValueError("VLM_CONTRACT_INCLUDES_MAPBOX_RGB")
    if mode == SentinelFetchMode.MINIMAL_RGB:
        raise ValueError("MINIMAL_RGB_UNSUPPORTED_USE_TERRAMIND_SPECTRAL")
    return materialize_spectral_paths(req, contract=contract)


def materialize_spectral_paths(
    req: MaterializeRequest,
    *,
    contract: VlmContract,
) -> MaterializeResult:
    """``TERRAMIND_SPECTRAL`` / ``FULL_STAC``: Sentinel-2 stack (P2)."""
    tim_branch = TimBranch(req.tim_branch)
    if req.enable_tim and tim_branch == TimBranch.RGB_MAPBOX and "mapbox_rgb" not in contract.roles:
        raise ValueError("TIM_RGB_REQUIRES_MAPBOX_VLM_CONTRACT")

    raw_png = b""
    attribution = "none"
    zoom = float(_clamp_zoom(req.mapbox_zoom))
    mw = _clamp_mapbox_size(req.mapbox_size)
    mh = mw
    mid = str(uuid.uuid4())
    cache_key = compute_cache_key(req)

    profile = AnalysisProfile(req.analysis_profile)
    profile_policy = profile_materialization_policy(profile)
    dt = (req.datetime_interval or "").strip() or default_datetime_interval(profile_policy["datetime_window_days"])
    include_scl = "cloud_mask_thumb" in contract.roles
    temporal_patches: dict[str, tuple[Any, dict[str, Any], Any | None]] = {}
    try:
        for label, interval, scene_id in temporal_scene_specs(
            req,
            profile=profile,
            datetime_interval=dt,
            window_days=int(profile_policy["datetime_window_days"]),
        ):
            patch = load_s2l2a_patch_np(
                lat=req.latitude,
                lon=req.longitude,
                datetime_range=interval,
                stac_url=req.stac_url.strip(),
                collection=req.collection_id.strip(),
                half_km=float(req.bbox_half_km),
                patch_hw=TIM_PATCH_HW,
                max_cloud=float(req.max_cloud_cover),
                asset_keys=s2_band_asset_keys(),
                max_items=20,
                include_scl=include_scl and label == "t1",
                scene_id=scene_id,
            )
            patch_stack, patch_meta, patch_scl = _patch_result_parts(patch)
            temporal_patches[label] = (patch_stack, dict(patch_meta, temporal_slice=label), patch_scl)
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

    temporal_stacks = {label: apply_reflectance_scale(patch_stack, {}) for label, (patch_stack, _meta, _scl) in temporal_patches.items()}
    stack, stac_meta, scl_patch = temporal_patches.get("t1") or next(iter(temporal_patches.values()))
    stack = temporal_stacks.get("t1", apply_reflectance_scale(stack, {}))
    temporal_metas = {label: meta for label, (_stack, meta, _scl) in temporal_patches.items()}

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
        temporal_stac_meta=temporal_metas,
        temporal_stacks=temporal_stacks,
    )


def scene_provenance_from_stac_meta(
    temporal_stac_meta: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if not temporal_stac_meta:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for label in sorted(temporal_stac_meta):
        meta = temporal_stac_meta[label]
        item_id = meta.get("stac_item_id")
        if not item_id:
            continue
        out[label] = {
            "item_id": item_id,
            "datetime": meta.get("stac_datetime"),
            "cloud_pct": meta.get("eo_cloud_cover"),
            "scene_id_requested": meta.get("scene_id_requested"),
            "quality": {
                "eo_cloud_cover": meta.get("eo_cloud_cover"),
                "scl_asset_key": meta.get("scl_asset_key"),
                "reference_asset": meta.get("reference_asset"),
                "band_asset_count": len(meta.get("band_asset_keys") or []),
            },
        }
    return out


def _patch_result_parts(patch: Any) -> tuple[Any, dict[str, Any], Any | None]:
    if hasattr(patch, "stack") and hasattr(patch, "meta"):
        return patch.stack, dict(patch.meta), getattr(patch, "scl_patch", None)
    stack, meta, scl_patch = patch
    return stack, dict(meta), scl_patch


def profile_artifacts(
    *,
    profile: AnalysisProfile,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
    existing_roles: list[str],
    vlm_contract_id: str,
    temporal_stacks: dict[str, Any] | None = None,
) -> list[VlmArtifact]:
    if profile == AnalysisProfile.BRIEF_ONLY:
        return []
    overlay_role = f"{profile.value}_aoi_overlay"
    extra_artifacts = []
    if profile == AnalysisProfile.WILDFIRE:
        extra_artifacts = _firewatch_artifacts(bbox=bbox, scene_provenance=scene_provenance, temporal_stacks=temporal_stacks)
    elif profile == AnalysisProfile.OCEANSCOUT_SHIP_DETECTION:
        extra_artifacts = _oceanscout_artifacts(bbox=bbox, scene_provenance=scene_provenance, temporal_stacks=temporal_stacks)
    elif profile == AnalysisProfile.LAND_USE_CHANGE:
        extra_artifacts = _landshift_artifacts(bbox=bbox, scene_provenance=scene_provenance, temporal_stacks=temporal_stacks)
    elif profile == AnalysisProfile.FLOOD_PULSE:
        extra_artifacts = _floodpulse_artifacts(bbox=bbox, scene_provenance=scene_provenance, temporal_stacks=temporal_stacks)
    extra_roles = [artifact.role for artifact in extra_artifacts]
    generated_roles = ["scene_provenance", overlay_role, *extra_roles, "profile_artifact_index"]
    index_payload = {
        "schema_version": "nutonic.pro.profile_artifact_index.v1",
        "analysis_profile": profile.value,
        "vlm_contract_id": vlm_contract_id,
        "scene_provenance_ref": "scene_provenance",
        "overlay_refs": [overlay_role, *[role for role in extra_roles if "heatmap" in role or "geojson" in role]],
        "source_roles": existing_roles,
        "generated_roles": generated_roles,
        "claim_safety": _profile_claim_safety(profile),
    }
    return [
        _json_artifact("scene_provenance", scene_provenance),
        _geojson_artifact(overlay_role, _profile_overlay_geojson(profile=profile, bbox=bbox, scene_provenance=scene_provenance)),
        *extra_artifacts,
        _json_artifact("profile_artifact_index", index_payload),
    ]


def _json_artifact(role: str, payload: dict[str, Any]) -> VlmArtifact:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return VlmArtifact(
        role=role,
        sha256=hashlib.sha256(raw).hexdigest(),
        mime="application/json",
        width=0,
        height=0,
        inline_base64=base64.standard_b64encode(raw).decode("ascii"),
    )


def _geojson_artifact(role: str, payload: dict[str, Any]) -> VlmArtifact:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return VlmArtifact(
        role=role,
        sha256=hashlib.sha256(raw).hexdigest(),
        mime="application/geo+json",
        width=0,
        height=0,
        inline_base64=base64.standard_b64encode(raw).decode("ascii"),
    )


def _png_artifact(role: str, png_bytes: bytes, *, width: int, height: int) -> VlmArtifact:
    return VlmArtifact(
        role=role,
        sha256=hashlib.sha256(png_bytes).hexdigest(),
        mime="image/png",
        width=width,
        height=height,
        inline_base64=base64.standard_b64encode(png_bytes).decode("ascii"),
    )


def _firewatch_artifacts(
    *,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
    temporal_stacks: dict[str, Any] | None,
) -> list[VlmArtifact]:
    if not temporal_stacks or "t0" not in temporal_stacks or "t1" not in temporal_stacks:
        return []
    delta = _burn_change_delta(temporal_stacks["t0"], temporal_stacks["t1"])
    if delta is None:
        return []
    metrics = _firewatch_metrics(delta, scene_provenance)
    hotspots = _firewatch_hotspots(delta, bbox)
    heatmap_png = _firewatch_heatmap_png(delta)
    metrics["hotspot_count"] = len(hotspots)
    metrics["hotspots_ref"] = "firewatch_hotspots"
    metrics["heatmap_ref"] = "firewatch_burn_change_heatmap"
    return [
        _png_artifact("firewatch_burn_change_heatmap", heatmap_png, width=delta.shape[1], height=delta.shape[0]),
        _json_artifact("firewatch_metrics", metrics),
        _json_artifact("firewatch_hotspots", {"schema_version": "nutonic.pro.firewatch.hotspots.v1", "hotspots": hotspots}),
        _geojson_artifact("firewatch_hotspots_geojson", _firewatch_hotspots_geojson(hotspots, scene_provenance)),
    ]


def _burn_change_delta(t0_stack: Any, t1_stack: Any) -> np.ndarray | None:
    a = np.asarray(t0_stack, dtype=np.float32)
    b = np.asarray(t1_stack, dtype=np.float32)
    if a.ndim != 3 or b.ndim != 3 or a.shape[0] < 12 or b.shape[0] < 12:
        return None
    nir_i, swir_i = 7, 11
    nbr0 = _normalized_difference(a[nir_i], a[swir_i])
    nbr1 = _normalized_difference(b[nir_i], b[swir_i])
    delta = nbr0 - nbr1
    return np.nan_to_num(delta, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _normalized_difference(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    denom = left + right
    return np.divide(left - right, denom, out=np.zeros_like(left, dtype=np.float32), where=np.abs(denom) > 1e-6)


def _firewatch_metrics(delta: np.ndarray, scene_provenance: dict[str, dict[str, Any]]) -> dict[str, Any]:
    positive = delta[delta > 0.0]
    threshold = _finite_percentile(positive, 85.0, fallback=0.1)
    high_threshold = _finite_percentile(positive, 97.0, fallback=max(threshold, 0.2))
    changed = delta >= threshold
    high = delta >= high_threshold
    return {
        "schema_version": "nutonic.pro.firewatch.metrics.v1",
        "changed_area_pct": _pct_int(int(changed.sum()), int(delta.size)),
        "high_signal_area_pct": _pct_int(int(high.sum()), int(delta.size)),
        "mean_burn_signal": round(float(np.mean(np.clip(delta, 0.0, None))), 6),
        "max_burn_signal": round(float(np.max(delta)), 6),
        "thresholds": {
            "nbr_delta_changed": round(float(threshold), 6),
            "nbr_delta_high": round(float(high_threshold), 6),
            "metric": "NBR(t0)-NBR(t1)",
        },
        "scene_ids": {
            label: scene.get("item_id")
            for label, scene in scene_provenance.items()
            if scene.get("item_id")
        },
    }


def _pct_int(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((count / total) * 100.0, 3)


def _finite_percentile(values: np.ndarray, pct: float, *, fallback: float) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return fallback
    return max(float(np.percentile(finite, pct)), fallback)


def _firewatch_hotspots(delta: np.ndarray, bbox: dict[str, float], *, grid: int = 8, limit: int = 12) -> list[dict[str, Any]]:
    height, width = delta.shape
    cells: list[dict[str, Any]] = []
    for gy in range(grid):
        y0 = int(round(gy * height / grid))
        y1 = int(round((gy + 1) * height / grid))
        for gx in range(grid):
            x0 = int(round(gx * width / grid))
            x1 = int(round((gx + 1) * width / grid))
            cell = delta[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            score = float(np.mean(np.clip(cell, 0.0, None)))
            if score <= 0.0:
                continue
            lon = bbox["west"] + ((gx + 0.5) / grid) * (bbox["east"] - bbox["west"])
            lat = bbox["north"] - ((gy + 0.5) / grid) * (bbox["north"] - bbox["south"])
            cells.append(
                {
                    "hotspot_id": f"fw-{gy:02d}-{gx:02d}",
                    "center_lat": round(lat, 6),
                    "center_lon": round(lon, 6),
                    "score": round(score, 6),
                    "confidence": _hotspot_confidence(score),
                    "grid_cell": {"x": gx, "y": gy, "grid": grid},
                    "evidence": ["nbr_delta", "sentinel_2_l2a_temporal_pair"],
                },
            )
    cells.sort(key=lambda row: float(row["score"]), reverse=True)
    return cells[:limit]


def _hotspot_confidence(score: float) -> str:
    if score >= 0.35:
        return "high"
    if score >= 0.18:
        return "medium"
    return "low"


def _firewatch_heatmap_png(delta: np.ndarray) -> bytes:
    positive = np.clip(delta, 0.0, None)
    hi = _finite_percentile(positive, 98.0, fallback=1.0)
    scaled = np.clip(positive / max(hi, 1e-6), 0.0, 1.0)
    rgba = np.zeros((delta.shape[0], delta.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = (scaled * 255.0).astype(np.uint8)
    rgba[..., 1] = (scaled * 120.0).astype(np.uint8)
    rgba[..., 3] = (scaled * 210.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _firewatch_hotspots_geojson(
    hotspots: list[dict[str, Any]],
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "firewatch_hotspots",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    **hotspot,
                    "scene_ids": {
                        label: scene.get("item_id")
                        for label, scene in scene_provenance.items()
                        if scene.get("item_id")
                    },
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [hotspot["center_lon"], hotspot["center_lat"]],
                },
            }
            for hotspot in hotspots
        ],
    }


def _oceanscout_artifacts(
    *,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
    temporal_stacks: dict[str, Any] | None,
) -> list[VlmArtifact]:
    if not temporal_stacks:
        return []
    stack = temporal_stacks["t1"] if "t1" in temporal_stacks else next(iter(temporal_stacks.values()))
    signal = _oceanscout_signal(stack)
    if signal is None:
        return []
    coverage = _oceanscout_observation_coverage(signal, scene_provenance)
    candidates = _oceanscout_candidates(signal, bbox, valid_observation_count=int(coverage["valid_observation_count"]))
    overlay = _oceanscout_candidate_geojson(candidates, scene_provenance)
    heatmap_png = _oceanscout_heatmap_png(signal)
    incursion_events = _oceanscout_incursion_events(candidates)
    return [
        _json_artifact("observation_coverage", coverage),
        _json_artifact("vessel_candidates", {"schema_version": "nutonic.pro.oceanscout.vessel_candidates.v1", "candidates": candidates}),
        _geojson_artifact("vessel_overlay", overlay),
        _png_artifact("lane_heatmap", heatmap_png, width=signal.shape[1], height=signal.shape[0]),
        _json_artifact("incursion_events", incursion_events),
    ]


def _oceanscout_signal(stack: Any) -> np.ndarray | None:
    arr = np.asarray(stack, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] < 12:
        return None
    green_i, nir_i, swir_i = 2, 7, 11
    ndwi = _normalized_difference(arr[green_i], arr[nir_i])
    pseudo_sar = np.abs(_normalized_difference(arr[swir_i], arr[nir_i]))
    water_mask = ndwi > 0.0
    signal = np.where(water_mask, pseudo_sar, pseudo_sar * 0.35)
    return np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _oceanscout_observation_coverage(
    signal: np.ndarray,
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cloud_values = [
        float(scene["cloud_pct"])
        for scene in scene_provenance.values()
        if isinstance(scene.get("cloud_pct"), (int, float))
    ]
    avg_cloud = sum(cloud_values) / len(cloud_values) if cloud_values else 0.0
    total = int(signal.size)
    cloud_masked = int(round(total * avg_cloud / 100.0))
    valid = max(0, total - cloud_masked)
    return {
        "schema_version": "nutonic.pro.oceanscout.observation_coverage.v1",
        "valid_observation_count": valid,
        "cloud_masked_count": cloud_masked,
        "glint_limited_count": None,
        "no_observation_count": 0,
        "normalization": "valid_observation_count",
        "scene_count": len(scene_provenance),
        "avg_cloud_pct": round(avg_cloud, 3),
    }


def _oceanscout_candidates(
    signal: np.ndarray,
    bbox: dict[str, float],
    *,
    valid_observation_count: int,
    grid: int = 10,
    limit: int = 20,
) -> list[dict[str, Any]]:
    height, width = signal.shape
    threshold = _finite_percentile(signal.reshape(-1), 94.0, fallback=0.15)
    candidates: list[dict[str, Any]] = []
    for gy in range(grid):
        y0 = int(round(gy * height / grid))
        y1 = int(round((gy + 1) * height / grid))
        for gx in range(grid):
            x0 = int(round(gx * width / grid))
            x1 = int(round((gx + 1) * width / grid))
            cell = signal[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            score = float(np.max(cell))
            if score < threshold:
                continue
            lon = bbox["west"] + ((gx + 0.5) / grid) * (bbox["east"] - bbox["west"])
            lat = bbox["north"] - ((gy + 0.5) / grid) * (bbox["north"] - bbox["south"])
            normalized_score = score / max(float(np.max(signal)), 1e-6)
            candidates.append(
                {
                    "candidate_id": f"os-{gy:02d}-{gx:02d}",
                    "center_lat": round(lat, 6),
                    "center_lon": round(lon, 6),
                    "confidence": _candidate_confidence(normalized_score),
                    "score": round(normalized_score, 6),
                    "evidence_level": "tim_pseudosar_plus_lulc",
                    "source_layers": ["sentinel_2_l2a", "tim_pseudo_sar_signal", "water_mask_proxy"],
                    "normalization_denominator": valid_observation_count,
                    "claim_safety": "presence_indicator_not_legal_assertion",
                },
            )
    candidates.sort(key=lambda row: float(row["score"]), reverse=True)
    return candidates[:limit]


def _candidate_confidence(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _oceanscout_candidate_geojson(
    candidates: list[dict[str, Any]],
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "oceanscout_vessel_overlay",
        "properties": {
            "base_model_color": "green",
            "tim_enhanced_color": "blue",
            "limitations": _profile_claim_safety(AnalysisProfile.OCEANSCOUT_SHIP_DETECTION)["limitations"],
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    **candidate,
                    "scene_ids": {
                        label: scene.get("item_id")
                        for label, scene in scene_provenance.items()
                        if scene.get("item_id")
                    },
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [candidate["center_lon"], candidate["center_lat"]],
                },
            }
            for candidate in candidates
        ],
    }


def _oceanscout_heatmap_png(signal: np.ndarray) -> bytes:
    hi = _finite_percentile(signal.reshape(-1), 98.0, fallback=1.0)
    scaled = np.clip(signal / max(hi, 1e-6), 0.0, 1.0)
    rgba = np.zeros((signal.shape[0], signal.shape[1], 4), dtype=np.uint8)
    rgba[..., 1] = (scaled * 180.0).astype(np.uint8)
    rgba[..., 2] = (scaled * 255.0).astype(np.uint8)
    rgba[..., 3] = (scaled * 210.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _oceanscout_incursion_events(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "nutonic.pro.oceanscout.incursion_events.v1",
        "events": [],
        "candidate_count": len(candidates),
        "policy": "No geofence configured; candidates remain presence indicators only.",
    }


_LAND_CLASSES = {
    0: "water",
    1: "vegetation",
    2: "built_or_bare",
    3: "low_signal",
}


def _landshift_artifacts(
    *,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
    temporal_stacks: dict[str, Any] | None,
) -> list[VlmArtifact]:
    if not temporal_stacks or "t0" not in temporal_stacks or "t1" not in temporal_stacks:
        return []
    c0 = _land_class_proxy(temporal_stacks["t0"])
    c1 = _land_class_proxy(temporal_stacks["t1"])
    if c0 is None or c1 is None:
        return []
    changed = c0 != c1
    matrix, top_transitions = _land_transition_summary(c0, c1)
    hotspots = _land_change_hotspots(changed, bbox)
    heatmap_png = _binary_heatmap_png(changed, color=(190, 120, 255))
    payload = {
        "schema_version": "nutonic.pro.landshift.transition_matrix.v1",
        "classes": _LAND_CLASSES,
        "matrix": matrix,
        "top_transitions": top_transitions,
        "changed_area_pct": _pct_int(int(changed.sum()), int(changed.size)),
        "scene_ids": {
            label: scene.get("item_id")
            for label, scene in scene_provenance.items()
            if scene.get("item_id")
        },
    }
    return [
        _json_artifact("land_transition_matrix", payload),
        _json_artifact("land_top_transitions", {"schema_version": "nutonic.pro.landshift.top_transitions.v1", "top_transitions": top_transitions}),
        _geojson_artifact("land_change_hotspots", _land_change_hotspots_geojson(hotspots, scene_provenance)),
        _png_artifact("land_change_heatmap", heatmap_png, width=changed.shape[1], height=changed.shape[0]),
    ]


def _land_class_proxy(stack: Any) -> np.ndarray | None:
    arr = np.asarray(stack, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] < 12:
        return None
    red_i, green_i, nir_i, swir_i = 3, 2, 7, 11
    ndvi = _normalized_difference(arr[nir_i], arr[red_i])
    ndwi = _normalized_difference(arr[green_i], arr[nir_i])
    ndbi = _normalized_difference(arr[swir_i], arr[nir_i])
    klass = np.full(ndvi.shape, 3, dtype=np.uint8)
    klass[ndwi > 0.12] = 0
    klass[(ndvi > 0.25) & (ndwi <= 0.12)] = 1
    klass[(ndbi > 0.12) & (ndwi <= 0.12) & (ndvi <= 0.25)] = 2
    return klass


def _land_transition_summary(c0: np.ndarray, c1: np.ndarray) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    top: list[dict[str, Any]] = []
    total = int(c0.size)
    for from_id, from_label in _LAND_CLASSES.items():
        for to_id, to_label in _LAND_CLASSES.items():
            count = int(np.logical_and(c0 == from_id, c1 == to_id).sum())
            row = {
                "from": from_label,
                "to": to_label,
                "count": count,
                "pct": _pct_int(count, total),
            }
            rows.append(row)
            if from_id != to_id and count > 0:
                top.append(row)
    top.sort(key=lambda row: int(row["count"]), reverse=True)
    return rows, top[:8]


def _land_change_hotspots(changed: np.ndarray, bbox: dict[str, float], *, grid: int = 8, limit: int = 12) -> list[dict[str, Any]]:
    height, width = changed.shape
    hotspots: list[dict[str, Any]] = []
    for gy in range(grid):
        y0 = int(round(gy * height / grid))
        y1 = int(round((gy + 1) * height / grid))
        for gx in range(grid):
            x0 = int(round(gx * width / grid))
            x1 = int(round((gx + 1) * width / grid))
            cell = changed[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            pct_changed = float(cell.mean())
            if pct_changed <= 0.0:
                continue
            lon = bbox["west"] + ((gx + 0.5) / grid) * (bbox["east"] - bbox["west"])
            lat = bbox["north"] - ((gy + 0.5) / grid) * (bbox["north"] - bbox["south"])
            hotspots.append(
                {
                    "hotspot_id": f"ls-{gy:02d}-{gx:02d}",
                    "center_lat": round(lat, 6),
                    "center_lon": round(lon, 6),
                    "changed_pct": round(pct_changed * 100.0, 3),
                    "evidence": ["land_class_proxy_t0_t1"],
                },
            )
    hotspots.sort(key=lambda row: float(row["changed_pct"]), reverse=True)
    return hotspots[:limit]


def _land_change_hotspots_geojson(
    hotspots: list[dict[str, Any]],
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "land_change_hotspots",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    **hotspot,
                    "scene_ids": {
                        label: scene.get("item_id")
                        for label, scene in scene_provenance.items()
                        if scene.get("item_id")
                    },
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [hotspot["center_lon"], hotspot["center_lat"]],
                },
            }
            for hotspot in hotspots
        ],
    }


def _binary_heatmap_png(mask: np.ndarray, *, color: tuple[int, int, int]) -> bytes:
    scaled = mask.astype(np.float32)
    rgba = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = (scaled * color[0]).astype(np.uint8)
    rgba[..., 1] = (scaled * color[1]).astype(np.uint8)
    rgba[..., 2] = (scaled * color[2]).astype(np.uint8)
    rgba[..., 3] = (scaled * 210.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _floodpulse_artifacts(
    *,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
    temporal_stacks: dict[str, Any] | None,
) -> list[VlmArtifact]:
    if not temporal_stacks or "t0" not in temporal_stacks or "t1" not in temporal_stacks:
        return []
    before = _water_mask_proxy(temporal_stacks["t0"])
    after = _water_mask_proxy(temporal_stacks["t1"])
    if before is None or after is None:
        return []
    expanded = np.logical_and(after, np.logical_not(before))
    receded = np.logical_and(before, np.logical_not(after))
    polygons = _flood_inundation_polygons(expanded, bbox)
    metrics = {
        "schema_version": "nutonic.pro.floodpulse.water_change_metrics.v1",
        "before_water_pct": _pct_int(int(before.sum()), int(before.size)),
        "after_water_pct": _pct_int(int(after.sum()), int(after.size)),
        "expanded_area_pct": _pct_int(int(expanded.sum()), int(expanded.size)),
        "receded_area_pct": _pct_int(int(receded.sum()), int(receded.size)),
        "inundation_polygon_count": len(polygons),
        "scene_ids": {
            label: scene.get("item_id")
            for label, scene in scene_provenance.items()
            if scene.get("item_id")
        },
    }
    return [
        _json_artifact("flood_water_change_metrics", metrics),
        _geojson_artifact("flood_inundation_polygons", _flood_polygons_geojson(polygons, scene_provenance)),
        _png_artifact("flood_before_water_extent", _binary_heatmap_png(before, color=(0, 120, 255)), width=before.shape[1], height=before.shape[0]),
        _png_artifact("flood_after_water_extent", _binary_heatmap_png(after, color=(0, 190, 255)), width=after.shape[1], height=after.shape[0]),
        _png_artifact("flood_expansion_heatmap", _binary_heatmap_png(expanded, color=(0, 255, 255)), width=expanded.shape[1], height=expanded.shape[0]),
    ]


def _water_mask_proxy(stack: Any) -> np.ndarray | None:
    arr = np.asarray(stack, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] < 8:
        return None
    green_i, nir_i = 2, 7
    ndwi = _normalized_difference(arr[green_i], arr[nir_i])
    return ndwi > 0.12


def _flood_inundation_polygons(expanded: np.ndarray, bbox: dict[str, float], *, grid: int = 8, limit: int = 16) -> list[dict[str, Any]]:
    height, width = expanded.shape
    cells: list[dict[str, Any]] = []
    for gy in range(grid):
        y0 = int(round(gy * height / grid))
        y1 = int(round((gy + 1) * height / grid))
        for gx in range(grid):
            x0 = int(round(gx * width / grid))
            x1 = int(round((gx + 1) * width / grid))
            cell = expanded[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            expanded_pct = float(cell.mean()) * 100.0
            if expanded_pct <= 0.0:
                continue
            west = bbox["west"] + (gx / grid) * (bbox["east"] - bbox["west"])
            east = bbox["west"] + ((gx + 1) / grid) * (bbox["east"] - bbox["west"])
            north = bbox["north"] - (gy / grid) * (bbox["north"] - bbox["south"])
            south = bbox["north"] - ((gy + 1) / grid) * (bbox["north"] - bbox["south"])
            cells.append(
                {
                    "polygon_id": f"fp-{gy:02d}-{gx:02d}",
                    "expanded_pct": round(expanded_pct, 3),
                    "bbox": {"west": west, "south": south, "east": east, "north": north},
                },
            )
    cells.sort(key=lambda row: float(row["expanded_pct"]), reverse=True)
    return cells[:limit]


def _flood_polygons_geojson(
    polygons: list[dict[str, Any]],
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    scene_ids = {
        label: scene.get("item_id")
        for label, scene in scene_provenance.items()
        if scene.get("item_id")
    }
    features = []
    for polygon in polygons:
        bb = polygon["bbox"]
        features.append(
            {
                "type": "Feature",
                "properties": {k: v for k, v in polygon.items() if k != "bbox"} | {"scene_ids": scene_ids},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bb["west"], bb["south"]],
                            [bb["east"], bb["south"]],
                            [bb["east"], bb["north"]],
                            [bb["west"], bb["north"]],
                            [bb["west"], bb["south"]],
                        ],
                    ],
                },
            },
        )
    return {"type": "FeatureCollection", "name": "flood_inundation_polygons", "features": features}


def _profile_overlay_geojson(
    *,
    profile: AnalysisProfile,
    bbox: dict[str, float],
    scene_provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    west = bbox["west"]
    south = bbox["south"]
    east = bbox["east"]
    north = bbox["north"]
    return {
        "type": "FeatureCollection",
        "name": f"{profile.value}_aoi_overlay",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "analysis_profile": profile.value,
                    "overlay_kind": _profile_overlay_kind(profile),
                    "scene_ids": {
                        label: scene.get("item_id")
                        for label, scene in scene_provenance.items()
                        if scene.get("item_id")
                    },
                    "limitations": _profile_claim_safety(profile)["limitations"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ],
                    ],
                },
            },
        ],
    }


def _profile_overlay_kind(profile: AnalysisProfile) -> str:
    return {
        AnalysisProfile.WILDFIRE: "burn_change_aoi",
        AnalysisProfile.OCEANSCOUT_SHIP_DETECTION: "observation_coverage_aoi",
        AnalysisProfile.LAND_USE_CHANGE: "land_transition_aoi",
        AnalysisProfile.FLOOD_PULSE: "flood_extent_aoi",
        AnalysisProfile.BRIEF_ONLY: "brief_context_aoi",
    }[profile]


def _profile_claim_safety(profile: AnalysisProfile) -> dict[str, Any]:
    if profile == AnalysisProfile.OCEANSCOUT_SHIP_DETECTION:
        return {
            "evidence_level": "screening_signal",
            "limitations": [
                "Optical/TiM-derived evidence is not legal proof of vessel identity or activity.",
                "Candidate overlays require human review and observation-coverage context.",
            ],
        }
    return {
        "evidence_level": "screening_signal",
        "limitations": ["Profile overlays are decision-support artifacts and require source-scene review."],
    }


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
    temporal_stac_meta: dict[str, dict[str, Any]] | None,
    temporal_stacks: dict[str, Any] | None,
) -> MaterializeResult:
    mapbox_in_contract = "mapbox_rgb" in contract.roles
    vlm_png = (
        resize_png_to_rgb_square(raw_mapbox_png, contract.width, contract.height)
        if mapbox_in_contract
        else b""
    )
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

    profile = AnalysisProfile(req.analysis_profile)
    scene_provenance = scene_provenance_from_stac_meta(temporal_stac_meta or ({"t1": stac_meta} if stac_meta else None))
    artifacts.extend(
        profile_artifacts(
            profile=profile,
            bbox={"west": west, "south": south, "east": east, "north": north},
            scene_provenance=scene_provenance,
            existing_roles=[artifact.role for artifact in artifacts],
            vlm_contract_id=req.vlm_contract_id,
        temporal_stacks=temporal_stacks,
        ),
    )

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
            if not mapbox_in_contract:
                raise ValueError("TIM_RGB_REQUIRES_MAPBOX_VLM_CONTRACT")
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
        "mapbox_source": mapbox_source_metadata() if mapbox_in_contract else {"provider": "none", "note": "no_mapbox_rgb_in_vlm_contract"},
        "profile_policy": profile_materialization_policy(profile),
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
    if scene_provenance:
        manifest["scene_provenance"] = scene_provenance
        manifest["temporal_slices"] = sorted(scene_provenance.keys())

    return MaterializeResult(
        materialization_id=mid,
        cache_key=cache_key,
        vlm_artifacts=artifacts,
        tim_payload=tim_payload,
        run_manifest=manifest,
        errors=[],
        warnings=[],
    )
