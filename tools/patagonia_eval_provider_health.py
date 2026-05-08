"""TerraMind TiM provider health gate (decoupled from VLM scoring).

Classifies each TiM row as ``good`` / ``borderline`` / ``degenerate`` based on:
- Whether ``profile_analytics`` carries non-trivial body (transition counts, vessel
  candidates, etc.).
- Whether decoded TiM coordinates drift > ``coord_drift_km_threshold`` from the
  requested AOI WGS84 lat/lon (250 km default).
- Whether ``tim_modality_outputs`` carries any non-zero numeric samples.

The aggregate block is published under ``payload.provider_health.tim`` so the report
clearly separates *the provider's quality* from *the model's quality* (the actual
evaluation target).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


_DRIFT_THRESHOLD_KM = 250.0


HealthStatus = Literal["good", "borderline", "degenerate", "missing"]


@dataclass(frozen=True)
class TimHealth:
    target_id: str
    status: HealthStatus
    drift_km: float | None
    flags: tuple[str, ...] = field(default_factory=tuple)
    detail: dict[str, Any] = field(default_factory=dict)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return float(2 * R * math.asin(math.sqrt(min(1.0, a))))


def _profile_body_signal(pa: dict[str, Any], profile: str) -> bool:
    if not isinstance(pa, dict):
        return False
    if profile == "land_use_change":
        lt = pa.get("land_transition")
        if isinstance(lt, dict):
            top = lt.get("top_transitions") or []
            for r in top:
                if (
                    isinstance(r, dict)
                    and isinstance(r.get("count"), (int, float))
                    and float(r["count"]) > 0
                    and str(r.get("from")) != str(r.get("to"))
                ):
                    return True
            cd = lt.get("class_distribution") or []
            return len(cd) >= 2
    if profile == "wildfire":
        bc = pa.get("burn_change")
        return bool(isinstance(bc, dict) and (bc.get("hotspot_count") or bc.get("changed_area_pct")))
    if profile == "flood_pulse":
        wc = pa.get("water_change")
        return bool(isinstance(wc, dict) and (wc.get("inundation_polygon_count") or wc.get("expanded_area_pct")))
    if profile == "oceanscout_ship_detection":
        vc = pa.get("vessel_candidates") or []
        dss = pa.get("detection_score_summary") or {}
        return bool(vc) or (isinstance(dss, dict) and (dss.get("sample_count") or 0) > 0)
    if profile == "brief_only":
        summ = pa.get("summary") or {}
        return bool(isinstance(summ, dict) and (summ.get("dominant_tim_classes") or summ.get("largest_deltas")))
    return False


def _tim_modality_has_signal(tmo: dict[str, Any] | None) -> bool:
    if not isinstance(tmo, dict):
        return False
    for _name, block in tmo.items():
        if not isinstance(block, dict):
            continue
        sample = block.get("sample")
        if isinstance(sample, list) and any(
            isinstance(x, (int, float)) and abs(float(x)) > 1e-6 for x in sample
        ):
            return True
        cf = block.get("class_fractions")
        if isinstance(cf, dict) and any(
            isinstance(v, (int, float)) and float(v) > 0.0 for v in cf.values()
        ):
            return True
    return False


def _decoded_coords(tmo: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(tmo, dict):
        return None
    coord = tmo.get("Coordinates")
    if not isinstance(coord, dict):
        return None
    for la_key, lo_key in (
        ("decoded_latitude", "decoded_longitude"),
        ("latitude", "longitude"),
    ):
        lat = coord.get(la_key)
        lon = coord.get(lo_key)
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            continue
    return None


def assess_tim_row(
    *,
    target_id: str,
    tim_compact: dict[str, Any] | None,
    requested_lat: float,
    requested_lon: float,
    profile: str,
    coord_drift_km_threshold: float = _DRIFT_THRESHOLD_KM,
) -> TimHealth:
    """Classify a single TiM row's health for downstream gating."""
    if not isinstance(tim_compact, dict) or not tim_compact:
        return TimHealth(target_id=target_id, status="missing", drift_km=None, flags=("no_tim_payload",))

    tmo = tim_compact.get("tim_modality_outputs")
    pa = tim_compact.get("profile_analytics")

    decoded = _decoded_coords(tmo)
    drift = _haversine_km(decoded[0], decoded[1], requested_lat, requested_lon) if decoded else None

    body_rich = _profile_body_signal(pa or {}, profile)
    sample_signal = _tim_modality_has_signal(tmo)

    flags: list[str] = []
    detail: dict[str, Any] = {
        "profile": profile,
        "decoded_coords": decoded,
        "requested_coords": (requested_lat, requested_lon),
        "body_rich": body_rich,
        "sample_signal": sample_signal,
    }

    drift_bad = drift is not None and drift > coord_drift_km_threshold
    if drift_bad:
        flags.append(f"coord_drift>{int(coord_drift_km_threshold)}km")
    if not body_rich:
        flags.append("profile_analytics_body_empty")
    if not sample_signal:
        flags.append("tim_modality_outputs_zero_signal")

    if not flags:
        status: HealthStatus = "good"
    elif drift_bad and not body_rich and not sample_signal:
        status = "degenerate"
    elif drift_bad or (not body_rich and not sample_signal):
        status = "degenerate"
    else:
        status = "borderline"

    return TimHealth(target_id=target_id, status=status, drift_km=drift, flags=tuple(flags), detail=detail)


def aggregate(rows: Iterable[TimHealth]) -> dict[str, Any]:
    """Build the ``provider_health.tim`` block."""
    rows_l = list(rows)
    counts = {"good": 0, "borderline": 0, "degenerate": 0, "missing": 0}
    drifts: list[float] = []
    flag_counter: dict[str, int] = {}
    per_row: list[dict[str, Any]] = []
    for r in rows_l:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.drift_km is not None:
            drifts.append(r.drift_km)
        for f in r.flags:
            flag_counter[f] = flag_counter.get(f, 0) + 1
        per_row.append(
            {
                "target_id": r.target_id,
                "status": r.status,
                "drift_km": round(r.drift_km, 2) if r.drift_km is not None else None,
                "flags": list(r.flags),
            }
        )
    n = len(rows_l) or 1
    median_drift = sorted(drifts)[len(drifts) // 2] if drifts else None
    return {
        "n_rows": len(rows_l),
        "status_counts": counts,
        "status_pct": {k: round(v * 100.0 / n, 2) for k, v in counts.items()},
        "median_drift_km": round(median_drift, 2) if median_drift is not None else None,
        "max_drift_km": round(max(drifts), 2) if drifts else None,
        "flag_counts": dict(sorted(flag_counter.items(), key=lambda kv: -kv[1])),
        "rows": per_row,
        "verdict": "use_with_caution" if counts.get("degenerate", 0) > len(rows_l) // 2 else "ok",
    }
