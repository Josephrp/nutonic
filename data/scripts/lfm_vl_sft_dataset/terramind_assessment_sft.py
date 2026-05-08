"""Helpers for TerraMind-conditioned VLM assessment SFT rows (multi-image + capped TiM context)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from lfm_vl_sft_dataset.jsonl_format import make_multi_image_vlm_message, split_key
from lfm_vl_sft_dataset.pro_prompts import PRO_ASSESSMENT_TASK_FOOTER, SYSTEM_ASSESSMENT

# Ordered roles for stable image ordering in user messages (PRO materialization contract).
VLM_ROLE_ORDER: tuple[str, ...] = ("sentinel_fc", "cloud_mask_thumb", "mapbox_rgb")

# Heuristic: first-party sensor / basemap views vs profile "prediction" overlays (heatmaps, candidates, …).
_RAW_IMAGE_ROLE_SUBSTRINGS: tuple[str, ...] = (
    "sentinel_fc",
    "cloud_mask_thumb",
    "mapbox_rgb",
)


def _is_raw_sensor_role(role: str) -> bool:
    r = role.lower()
    return any(tok in r for tok in _RAW_IMAGE_ROLE_SUBSTRINGS)


def _is_profile_overlay_role(role: str) -> bool:
    if _is_raw_sensor_role(role):
        return False
    r = role.lower()
    if r in ("scene_provenance", "profile_artifact_index"):
        return False
    return (
        "heatmap" in r
        or "overlay" in r
        or r.startswith("firewatch_")
        or r.startswith("vessel_")
        or r.startswith("lane_")
        or r.startswith("incursion_")
        or r.startswith("observation_")
        or r.startswith("land_")
        or r.startswith("flood_")
    )


def _is_decodable_raster_artifact(art: Mapping[str, Any]) -> bool:
    if not isinstance(art, Mapping):
        return False
    mime = str(art.get("mime") or "").lower().strip()
    if not mime.startswith("image/"):
        return False
    if mime in ("image/svg+xml",):
        return False
    w = art.get("width")
    h = art.get("height")
    if isinstance(w, int) and isinstance(h, int) and (w < 1 or h < 1):
        return False
    b64 = art.get("inline_base64")
    return isinstance(b64, str) and bool(b64.strip())


def lat_lon_from_materialize_bbox(materialize: Mapping[str, Any]) -> tuple[float, float] | None:
    """Approximate AOI center from ``run_manifest.bbox_wgs84`` if present."""
    rm = materialize.get("run_manifest")
    if not isinstance(rm, dict):
        return None
    bb = rm.get("bbox_wgs84")
    if not isinstance(bb, dict):
        return None
    west, south, east, north = bb.get("west"), bb.get("south"), bb.get("east"), bb.get("north")
    if not all(isinstance(x, (int, float)) for x in (west, south, east, north)):
        return None
    return float(south + north) / 2.0, float(west + east) / 2.0

FORBIDDEN_SUBSTRINGS = (
    "illegal activity",
    "confirmed vessel",
    "definitely illegal",
    "ground truth",
)


def _json_bytes(obj: dict[str, Any] | None) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign_post_headers(url: str, body: bytes) -> dict[str, str]:
    """POST signing aligned with ``server/src/nutonic_server/inference_client.py``."""
    sec = (os.environ.get("NUTONIC_INFERENCE_HMAC_SECRET") or os.environ.get("INFERENCE_HMAC_SECRET") or "").strip()
    if not sec:
        # ``requests`` does not infer JSON when posting raw bytes; FastAPI expects this header.
        return {"Content-Type": "application/json"}
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{ts}\n{nonce}\nPOST\n{path}\n{body_hash}\n"
    sig = hmac.new(sec.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Nutonic-Timestamp": ts,
        "X-Nutonic-Nonce": nonce,
        "X-Nutonic-Content-SHA256": body_hash,
        "X-Nutonic-Signature": sig,
        "Content-Type": "application/json",
    }


_TRAINING_TIM_DENY_KEYS: frozenset[str] = frozenset(
    {
        "_inputs",
        "_internal_coords",
        "patch_diagnostics",
        "tensor",
        "x",
        "emb",
        "embeddings",
        "masks",
        "token_ids",
        "ids",
        "decoder_attention_mask",
        "attention_mask",
    }
)


def _parse_bbox_wgs84_dict(bb: Any) -> dict[str, float] | None:
    if isinstance(bb, dict):
        w, s, e, n = bb.get("west"), bb.get("south"), bb.get("east"), bb.get("north")
        if all(isinstance(x, (int, float)) for x in (w, s, e, n)):
            return {"west": float(w), "south": float(s), "east": float(e), "north": float(n)}
        return None
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        w, s, e, n = bb
        if all(isinstance(x, (int, float)) for x in (w, s, e, n)):
            return {"west": float(w), "south": float(s), "east": float(e), "north": float(n)}
    return None


def tim_coordinates_within_manifest_bbox(
    lat: float,
    lon: float,
    bbox: dict[str, float],
    *,
    margin_deg: float = 1e-4,
) -> bool:
    """Return True if ``(lat, lon)`` lies inside ``bbox`` (west/south/east/north) with a small margin."""
    m = margin_deg
    return (
        bbox["south"] - m <= lat <= bbox["north"] + m
        and bbox["west"] - m <= lon <= bbox["east"] + m
    )


def remove_tim_coordinates_outside_manifest(
    tim_context: dict[str, Any],
    run_manifest_excerpt: Mapping[str, Any] | None,
    *,
    mark_out_of_footprint: bool = True,
) -> dict[str, Any]:
    """
    If TiM ``Coordinates`` disagree with ``run_manifest_excerpt['bbox_wgs84']``, drop that modality entry.

    Prevents teaching contradictory coordinate hints vs the materialized footprint.
    """
    out = dict(tim_context)
    tmo = out.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return out
    tmo = dict(tmo)
    out["tim_modality_outputs"] = tmo
    if not isinstance(run_manifest_excerpt, Mapping):
        return out
    bb = _parse_bbox_wgs84_dict(run_manifest_excerpt.get("bbox_wgs84"))
    if bb is None:
        return out
    coords = tmo.get("Coordinates")
    if not isinstance(coords, dict):
        return out
    lat, lon = coords.get("latitude"), coords.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return out
    if tim_coordinates_within_manifest_bbox(float(lat), float(lon), bb):
        return out
    tmo.pop("Coordinates", None)
    if mark_out_of_footprint:
        tmo["_coordinate_hint_suppressed"] = {
            "reason": "out_of_footprint",
            "detail": "TiM Coordinates fell outside run_manifest.bbox_wgs84 (plus tolerance).",
        }
    return out


def summarize_tim_context_for_training(obj: Any) -> Any:
    """
    Recursively remove TiM internals (tensor banks, traces, heavy engine blobs) before user prompts.

    Intended for **training / export hygiene**; call before ``cap_tim_context`` on live TiM payloads.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if isinstance(k, str) and k in _TRAINING_TIM_DENY_KEYS:
                    continue
                if (
                    isinstance(k, str)
                    and k.startswith("_")
                    and k not in ("_truncated", "_coordinate_hint_suppressed")
                ):
                    continue
                out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node[:200]]
        if isinstance(node, str) and len(node) > 2000:
            return node[:2000] + "…"
        return node

    slimmed = walk(obj)
    if isinstance(slimmed, dict) and isinstance(slimmed.get("engine"), dict):
        eng = slimmed["engine"]
        keep = {k: eng[k] for k in ("model_id", "variant", "version", "name") if k in eng}
        if keep:
            slimmed["engine"] = keep
        else:
            slimmed.pop("engine", None)
    return slimmed


def cap_tim_context(
    obj: Any,
    *,
    max_chars: int = 12_000,
    max_sample_len: int = 16,
    strip_keys: frozenset[str] = frozenset({"npz_base64", "inline_base64", "sample"}),
) -> Any:
    """Return JSON-serializable copy with secrets/large blobs removed and ``sample`` arrays truncated."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in strip_keys:
                    if k == "sample" and isinstance(v, list):
                        out[k] = [walk(x) for x in v[:max_sample_len]]
                    else:
                        out[k] = "<redacted>"
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node[:200]]
        if isinstance(node, str) and len(node) > 2000:
            return node[:2000] + "…"
        return node

    capped = walk(obj)
    text = json.dumps(capped, ensure_ascii=False)
    if len(text) <= max_chars:
        return capped
    return {"_truncated": True, "utf8_preview": text[:max_chars]}


def extract_tim_modality_block(tim_export_line: dict[str, Any]) -> dict[str, Any]:
    """Pick ``tim_modality_outputs`` (or whole line minus heavy keys) from a TiM export row."""
    out = dict(tim_export_line)
    out.pop("npz_base64", None)
    if "tim_modality_outputs" in out:
        return {"tim_modality_outputs": out["tim_modality_outputs"]}
    return {"tim_export": out}


def decode_vlm_artifacts_to_files(
    materialize: Mapping[str, Any],
    images_dir: Path,
    *,
    stem: str,
) -> tuple[list[str], str]:
    """
    Decode **all** raster ``vlm_artifacts`` (contract views + profile overlay PNGs) into ``images_dir``.

    ``images_dir`` must be the dataset ``images/`` folder (e.g. ``out_dir / "images"``), matching
    relative paths returned (``images/<file>`` from dataset root).

    Ordering: ``VLM_ROLE_ORDER`` roles first, then remaining ``image/*`` roles sorted by role name.

    Returns ``(relative_paths_in_order, canonical_surface_id)``.
    """
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    artifacts = materialize.get("vlm_artifacts") or []
    if not isinstance(artifacts, list):
        raise ValueError("materialize.vlm_artifacts must be a list")

    by_role: dict[str, dict[str, Any]] = {}
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        role = str(a.get("role") or "")
        if role:
            by_role[role] = a

    ordered_roles: list[str] = []
    for role in VLM_ROLE_ORDER:
        art = by_role.get(role)
        if art and _is_decodable_raster_artifact(art):
            ordered_roles.append(role)
    rest_png = sorted(
        role
        for role, art in by_role.items()
        if role not in ordered_roles and _is_decodable_raster_artifact(art)
    )
    ordered_roles.extend(rest_png)

    rel_paths: list[str] = []
    first_role: str | None = None
    for role in ordered_roles:
        art = by_role[role]
        b64 = art.get("inline_base64")
        if not isinstance(b64, str) or not b64.strip():
            continue
        raw = base64.b64decode(b64)
        mime = str(art.get("mime") or "").lower()
        if "jpeg" in mime or mime.endswith("/jpeg"):
            ext = ".jpg"
        elif "png" in mime or mime.endswith("/png"):
            ext = ".png"
        elif "webp" in mime:
            ext = ".webp"
        else:
            ext = ".bin"
        fname = f"{stem}_{role}{ext}"
        out_path = images_dir / fname
        out_path.write_bytes(raw)
        rel_paths.append(f"images/{fname}")
        if first_role is None:
            first_role = role

    if not rel_paths:
        raise ValueError("No decodable raster vlm_artifacts with inline_base64 found in materialize response")

    canonical = first_role or "mapbox_rgb"
    rm = materialize.get("run_manifest") or {}
    if isinstance(rm, dict):
        vc = rm.get("vlm_canvas") or {}
        if isinstance(vc, dict) and isinstance(vc.get("canonical_surface_id"), str):
            canonical = vc["canonical_surface_id"]

    return rel_paths, canonical, list(ordered_roles)


def materialize_role_png_bytes(materialize: Mapping[str, Any], role: str) -> bytes | None:
    """Return decoded PNG/JPEG bytes for ``role`` in ``vlm_artifacts``, if present and raster."""
    for a in materialize.get("vlm_artifacts") or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("role") or "") != role:
            continue
        if not _is_decodable_raster_artifact(a):
            return None
        b64 = a.get("inline_base64")
        if isinstance(b64, str) and b64.strip():
            return base64.b64decode(b64)
    return None


def write_mapbox_rgb_as_jpeg_for_tim(materialize: Mapping[str, Any], dest: Path) -> bool:
    """
    Write ``mapbox_rgb`` artifact to ``dest`` as JPEG for TiM ``inputs.mode=jpeg`` / ``rgb_jpeg``.

    Returns False if role missing or Pillow unavailable.
    """
    raw = materialize_role_png_bytes(materialize, "mapbox_rgb")
    if raw is None:
        return False
    try:
        import io

        from PIL import Image
    except ImportError:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.save(dest, format="JPEG", quality=92)
    return True


def save_e2e_fixture_bundle(
    dest_dir: Path,
    *,
    materialize: Mapping[str, Any],
    tim_export: Mapping[str, Any],
) -> None:
    """Persist live responses for later ``--offline-fixture`` / ``--materialize-json`` replay."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "materialize.json").write_text(
        json.dumps(materialize, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (dest_dir / "tim.json").write_text(
        json.dumps(tim_export, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def tim_infer_config_from_materialize(
    materialize: Mapping[str, Any],
    seed: Mapping[str, Any],
    mat_request: Mapping[str, Any] | None,
    *,
    model_id: str,
    device: str,
    tim_branch: str,
    rgb_jpeg_path: str | None = None,
) -> dict[str, Any]:
    """
    Build a TiM Space ``/v1/tim/infer`` body aligned with materialization AOI and STAC hints.

    Uses **STAC-backed** tensors (``s2_mode=stac`` / ``rgb_mode=s2_rgb``) when spectral modes were used;
    uses ``rgb_jpeg`` only for ``RGB_mapbox`` + ``MINIMAL_RGB`` when ``rgb_jpeg_path`` is provided.
    """
    rm = materialize.get("run_manifest") if isinstance(materialize.get("run_manifest"), dict) else {}
    mr = dict(mat_request or {})
    profile = str(seed.get("analysis_profile") or mr.get("analysis_profile") or "brief_only")
    map_id = str(seed.get("map_id") or "e2e_map")
    location_id = str(seed.get("location_id") or "e2e_loc")
    lat = float(seed["lat"])
    lon = float(seed["lon"])
    half_km = float(mr.get("bbox_half_km", 5.0))
    stac_url = str(mr.get("stac_url") or "https://earth-search.aws.element84.com/v1")
    collection_id = str(mr.get("collection_id") or "sentinel-2-l2a")
    max_cloud = float(mr.get("max_cloud_cover", 30.0))
    fetch_mode = str(mr.get("sentinel_fetch_mode") or "TERRAMIND_SPECTRAL")

    st = rm.get("stac") if isinstance(rm.get("stac"), dict) else {}
    dt_interval = mr.get("datetime_interval")
    datetime_s = ""
    if isinstance(dt_interval, str) and dt_interval.strip():
        datetime_s = dt_interval.strip()
    elif isinstance(st.get("datetime"), str) and st.get("datetime"):
        datetime_s = str(st["datetime"])

    s2_block: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "half_km": half_km,
        "stac_url": stac_url,
        "collection": collection_id,
        "max_cloud": max_cloud,
    }
    if datetime_s:
        s2_block["datetime"] = datetime_s
    sk = st.get("item_id")
    if isinstance(sk, str) and sk.strip():
        s2_block["scene_id"] = sk.strip()

    serialization = {
        "tensor_sample_limit": 32,
        "tim_outputs": "product",
        "include_encoder_trace": False,
    }
    export = {"map_id": map_id, "location_id": location_id, "include_ai_guess_row": False}
    base_cfg: dict[str, Any] = {
        "model_id": model_id,
        "pretrained": True,
        "tim_modalities": ["LULC", "location"],
        "merge_method": "mean",
        "device": device,
        "analysis_profile": profile,
        "serialization": serialization,
        "export": export,
    }

    branch = (tim_branch or "S2L2A_full").strip()
    spectral = fetch_mode in ("TERRAMIND_SPECTRAL", "FULL_STAC")

    if branch == "RGB_mapbox" and fetch_mode == "MINIMAL_RGB" and rgb_jpeg_path:
        return {
            "profile": profile,
            "config": {
                **base_cfg,
                "modalities": ["RGB"],
                "inputs": {
                    "batch_size": 1,
                    "mode": "jpeg",
                    "rgb_jpeg": rgb_jpeg_path,
                },
            },
        }

    if branch == "RGB_mapbox" and spectral:
        return {
            "profile": profile,
            "config": {
                **base_cfg,
                "modalities": ["RGB"],
                "inputs": {
                    "batch_size": 1,
                    "lat": lat,
                    "lon": lon,
                    "s2": dict(s2_block),
                    "by_modality": {"RGB": {"rgb_mode": "s2_rgb", "batch_size": 1}},
                },
            },
        }

    if branch == "RGB_mapbox" and fetch_mode == "MINIMAL_RGB" and not rgb_jpeg_path:
        raise ValueError(
            "TIM_RGB_MAPBOX_MINIMAL_REQUIRES_JPEG: mapbox_rgb → JPEG path missing (install Pillow and decode "
            "mapbox_rgb), or use --sentinel-fetch-mode TERRAMIND_SPECTRAL so TiM can use rgb_mode=s2_rgb.",
        )

    # Default: S2L2A full tensor from STAC (matches materialization chip policy).
    return {
        "profile": profile,
        "config": {
            **base_cfg,
            "modalities": ["S2L2A"],
            "inputs": {
                "batch_size": 1,
                "lat": lat,
                "lon": lon,
                "s2": dict(s2_block),
                "by_modality": {"S2L2A": {"s2_mode": "stac", "batch_size": 1}},
            },
        },
    }


def build_assessment_user_text(
    *,
    analysis_profile: str,
    canonical_surface_id: str,
    tim_context: dict[str, Any],
    run_manifest_excerpt: dict[str, Any] | None,
    brief_fuse: dict[str, Any] | None,
    tim_branch: str | None,
    image_roles: list[str] | None = None,
) -> str:
    parts = [
        "Assessment context:",
        f"- analysis_profile: {analysis_profile}",
        f"- canonical_surface_id: {canonical_surface_id}",
    ]
    if tim_branch:
        parts.append(f"- tim_input_branch: {tim_branch}")
    if image_roles:
        parts.append("- Image sequence (PRO materialization roles; same order as the image parts above):")
        for i, role in enumerate(image_roles, start=1):
            if _is_raw_sensor_role(role):
                tag = "raw / sensor or basemap view"
            elif _is_profile_overlay_role(role):
                tag = "profile or model-derived overlay / diagnostic raster"
            else:
                tag = "auxiliary raster"
            parts.append(f"  {i}. `{role}` — {tag}")
    parts.append("- TerraMind / TiM context (capped JSON, model evidence only):")
    parts.append(json.dumps(tim_context, ensure_ascii=False, indent=2))
    if run_manifest_excerpt:
        parts.append("- scene / run excerpt:")
        parts.append(json.dumps(run_manifest_excerpt, ensure_ascii=False, indent=2))
    if brief_fuse:
        parts.append("- optional brief composer summary (also model-generated):")
        parts.append(json.dumps(brief_fuse, ensure_ascii=False, indent=2))
    parts.append(PRO_ASSESSMENT_TASK_FOOTER)
    return "\n".join(parts)


def _coord_summary(
    tim_block: Mapping[str, Any],
    *,
    run_manifest_excerpt: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    tmo = tim_block.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return None, None
    coords = tmo.get("Coordinates")
    if not isinstance(coords, dict):
        return None, None
    lat = coords.get("latitude")
    lon = coords.get("longitude")
    conf = coords.get("confidence")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        bb = None
        if isinstance(run_manifest_excerpt, Mapping):
            bb = _parse_bbox_wgs84_dict(run_manifest_excerpt.get("bbox_wgs84"))
        if bb is not None and not tim_coordinates_within_manifest_bbox(float(lat), float(lon), bb):
            return None, None
        line = f"approximate coordinate hint lat={float(lat):.4f} lon={float(lon):.4f}"
        if isinstance(conf, (int, float)):
            line += f" (reported confidence {float(conf):.2f})"
        return line, "coordinates_wgs84"
    if coords.get("decode_error"):
        return f"coordinate decode note: {str(coords.get('decode_error'))[:200]}", "decode_error"
    return None, None


def build_deterministic_assistant_text(
    *,
    analysis_profile: str,
    tim_context: dict[str, Any],
    canonical_surface_id: str,
    run_manifest_excerpt: Mapping[str, Any] | None = None,
) -> str:
    """Rule-based assessment target (teacher placeholder) — conservative, no forbidden certainty."""
    tmo = tim_context.get("tim_modality_outputs")
    keys: list[str] = []
    if isinstance(tmo, dict):
        keys = sorted(k for k in tmo.keys() if isinstance(k, str) and not k.startswith("_"))[:24]
    coord_line, coord_kind = _coord_summary(tim_context, run_manifest_excerpt=run_manifest_excerpt)

    profile_note = {
        "wildfire": "Change-sensitive wildfire or burn-scar style interpretation may apply; verify against dates and clouds.",
        "oceanscout_ship_detection": "Maritime context: treat bright-water responses as **candidate** indicators only.",
        "land_use_change": "Land-cover transition claims need multi-date consistency checks.",
        "flood_pulse": "Water expansion signals are sensitive to atmospheric and seasonal effects.",
        "brief_only": "General-purpose AOI; emphasize evidence separation and limitations.",
    }.get(analysis_profile, "General AOI; emphasize evidence separation and limitations.")

    lines = [
        "Assessment:",
        "The scene combines overhead imagery with TerraMind-style modality summaries supplied as auxiliary evidence.",
        "Treat modality outputs as **model hypotheses** unless corroborated by independent observations.",
        "",
        "Evidence:",
        "- Visual evidence: Interpret structure and texture in the imagery sequence; note cloud or haze if visible.",
        "- TerraMind evidence: "
        + (f"Modality keys present: {', '.join(keys) or 'none listed'}." if keys else "No structured modality keys listed."),
    ]
    if coord_line:
        lines.append(f"  - {coord_kind or 'Coordinates'}: {coord_line}")
    lines.extend(
        [
            "",
            f"Profile guidance: {profile_note}",
            "",
            "Confidence: moderate — limited by optical-only constraints and uncorrected model drift.",
            "",
            "Limitations:",
            "- RGB_mapbox TiM tensors (when used) are **not** the same as Sentinel reflectance RGB; do not merge semantics.",
            "- Pseudo-SAR-like or TiM-enhanced indicators are not equivalent to SAR confirmation.",
            "",
            "Recommended follow-up:",
            "- Add independent temporal pairs or alternate sensors where risk decisions matter.",
            "- Compare model coordinate hints against the canonical image footprint before acting.",
            "",
            f"(canonical_surface_id for any normalized boxes: {canonical_surface_id})",
        ]
    )
    return "\n".join(lines)


def assert_assistant_conservative(text: str) -> None:
    low = text.lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in low, f"assistant text must not contain {bad!r}"


def build_assessment_row(
    *,
    sample_id: str,
    image_rel_paths: list[str],
    analysis_profile: str,
    canonical_surface_id: str,
    tim_context: dict[str, Any],
    run_manifest_excerpt: dict[str, Any] | None,
    brief_fuse: dict[str, Any] | None,
    tim_branch: str | None,
    source_mode: str,
    image_roles: list[str] | None = None,
) -> dict[str, Any]:
    user_text = build_assessment_user_text(
        analysis_profile=analysis_profile,
        canonical_surface_id=canonical_surface_id,
        tim_context=tim_context,
        run_manifest_excerpt=run_manifest_excerpt,
        brief_fuse=brief_fuse,
        tim_branch=tim_branch,
        image_roles=image_roles,
    )
    assistant = build_deterministic_assistant_text(
        analysis_profile=analysis_profile,
        tim_context=tim_context,
        canonical_surface_id=canonical_surface_id,
        run_manifest_excerpt=run_manifest_excerpt,
    )
    assert_assistant_conservative(assistant)
    row = make_multi_image_vlm_message(
        image_rel_paths,
        user_text,
        assistant,
        system_text=SYSTEM_ASSESSMENT,
        metadata={
            "sample_id": sample_id,
            "analysis_profile": analysis_profile,
            "canonical_surface_id": canonical_surface_id,
            "source_mode": source_mode,
            "n_images": len(image_rel_paths),
            "image_roles": list(image_roles or []),
        },
    )
    return row


def materialize_post(
    base_url: str,
    body: dict[str, Any],
    *,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    import requests

    url = f"{base_url.rstrip('/')}/internal/v1/materialize"
    raw = _json_bytes(body)
    headers = sign_post_headers(url, raw)
    r = requests.post(url, data=raw, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def brief_fuse_post(
    base_url: str,
    body: dict[str, Any],
    *,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    import requests

    url = f"{base_url.rstrip('/')}/v1/pro/brief/fuse"
    raw = _json_bytes(body)
    headers = sign_post_headers(url, raw)
    r = requests.post(url, data=raw, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def tim_infer_post(
    base_url: str,
    body: dict[str, Any],
    *,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    import requests

    url = f"{base_url.rstrip('/')}/v1/tim/infer"
    raw = _json_bytes(body)
    headers = sign_post_headers(url, raw)
    r = requests.post(url, data=raw, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def default_tim_infer_body(
    *,
    map_id: str,
    location_id: str,
    analysis_profile: str,
    model_id: str,
    device: str,
) -> dict[str, Any]:
    """Minimal CPU-friendly TiM request for dataset hydration (random RGB smoke)."""
    return {
        "profile": analysis_profile,
        "config": {
            "model_id": model_id,
            "pretrained": True,
            "modalities": ["RGB"],
            "tim_modalities": ["LULC", "location"],
            "merge_method": "mean",
            "device": device,
            "analysis_profile": analysis_profile,
            "inputs": {"mode": "random", "batch_size": 1},
            "serialization": {
                "tensor_sample_limit": 32,
                "tim_outputs": "product",
                "include_encoder_trace": False,
            },
            "export": {
                "map_id": map_id,
                "location_id": location_id,
                "include_ai_guess_row": False,
            },
        },
    }


def merge_tim_into_context(tim_infer_response: dict[str, Any]) -> dict[str, Any]:
    """Normalize TiM HTTP export (``run_tim_forward_export`` row) for ``cap_tim_context``."""
    out: dict[str, Any] = {}
    for k in ("tim_modality_outputs", "profile_analytics", "inputs_meta", "engine"):
        if k in tim_infer_response:
            out[k] = tim_infer_response[k]
    if out:
        return out
    for key in ("export", "result", "run"):
        inner = tim_infer_response.get(key)
        if isinstance(inner, dict) and "tim_modality_outputs" in inner:
            return merge_tim_into_context(inner)
    return {"tim_response_keys": sorted(tim_infer_response.keys())[:40]}


def load_seed_aois(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def run_manifest_excerpt_from_materialize(materialize: Mapping[str, Any]) -> dict[str, Any]:
    rm = materialize.get("run_manifest")
    if not isinstance(rm, dict):
        return {}
    keys = (
        "bbox_wgs84",
        "scene_provenance",
        "temporal_slices",
        "mapbox_attribution",
        "vlm_canvas",
        "s2_asset_mapping_version",
    )
    return {k: rm[k] for k in keys if k in rm}


def split_for_sample(sample_id: str) -> str:
    return split_key(sample_id)
