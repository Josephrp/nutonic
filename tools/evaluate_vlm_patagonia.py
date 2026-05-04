#!/usr/bin/env python3
"""
Patagonia-focused VLM evaluator (Los Alerces + marine reserves + control targets).

What it does:
1) Fetches reference stills per target — default **Sentinel-2 via Earth Search STAC** (see
   ``data/scripts/stac_reference_still.py``), or Mapbox Satellite static images via ``--still-source mapbox``.
2) Sends each image to one or more VLM endpoints (NU:TONIC satellite /v1/infer contract).
3) Scores captions against target-specific expected concepts.
4) Writes a machine-readable JSON report and prints a concise console summary.

**TiM E2E** (``tools/evaluate_vlm_patagonia_tim_e2e.py``) adds multimodal scoring: see
``tools/patagonia_eval_scoring.py`` (lexical + SCL IoU + structured + composite) and
``tools/patagonia_eval_gold.py`` (reference boxes from Sentinel-2 SCL).

Sources used for core geographies (investigation baseline):
- Los Alerces NP: SIB / National Parks / Wikipedia
- Yaganes MPA: SIB (APN Argentina)
- Namuncura-Banco Burdwood: APN/AMP Argentina boundary docs
- Parque Interjurisdiccional Marino Costero Patagonia Austral: SIB / APN
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install httpx first: pip install httpx") from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_SCRIPTS = REPO_ROOT / "data" / "scripts"
if str(_DATA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_DATA_SCRIPTS))

DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "downloads" / "evals"
DEFAULT_IMAGE_CACHE_DIR = DEFAULT_REPORT_DIR / "patagonia_stills"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if os.environ.get("NUTONIC_NO_DOTENV") == "1":
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()


def _space_url_from_repo_id(repo_id: str) -> str:
    slug = repo_id.strip().lower().replace("/", "-")
    return f"https://{slug}.hf.space"


def _default_satellite_endpoint() -> str:
    direct = (os.environ.get("NUTONIC_LFM_VL_SATELLITE_URL") or "").strip()
    if direct:
        return direct.rstrip("/")
    repo_id = (os.environ.get("NUTONIC_LFM_VL_SATELLITE_REPO_ID") or "").strip()
    return _space_url_from_repo_id(repo_id).rstrip("/") if repo_id else ""


def patagonia_comparison_hf_model_ids() -> dict[str, str]:
    """HF hub ids for finetune vs base satellite VLMs (local eval or one model per Space)."""
    return {
        "finetune": (os.environ.get("NUTONIC_PATAGONIA_EVAL_FINETUNE_MODEL_ID") or "NuTonic/lspace").strip(),
        "base": (os.environ.get("NUTONIC_PATAGONIA_EVAL_BASE_MODEL_ID") or "LiquidAI/LFM2.5-VL-450M").strip(),
    }


def resolve_patagonia_eval_endpoints(cli_endpoints: list[str]) -> list[tuple[str, str]]:
    """
    VLM /v1/infer endpoints for Patagonia eval.

    1) If ``cli_endpoints`` is non-empty, use those (``--endpoint name=url`` or URL only; repeatable).
    2) Else if both ``NUTONIC_PATAGONIA_EVAL_FINETUNE_URL`` and ``NUTONIC_PATAGONIA_EVAL_BASE_URL`` are set,
       return two named endpoints: **finetune** (``NuTonic/lspace``) and **base** (``LiquidAI/LFM2.5-VL-450M`` by default).
    3) Else fall back to a single default from ``NUTONIC_LFM_VL_SATELLITE_URL`` or
       ``NUTONIC_LFM_VL_SATELLITE_REPO_ID`` (HF Space).
    """
    if cli_endpoints:
        return _parse_endpoints(cli_endpoints, "")
    ft = (os.environ.get("NUTONIC_PATAGONIA_EVAL_FINETUNE_URL") or "").strip().rstrip("/")
    bs = (os.environ.get("NUTONIC_PATAGONIA_EVAL_BASE_URL") or "").strip().rstrip("/")
    if ft and bs:
        return [("finetune", ft), ("base", bs)]
    return _parse_endpoints([], _default_satellite_endpoint())


def write_patagonia_per_model_artifacts(
    out_dir: Path,
    *,
    results: list[dict[str, Any]],
    summary_by_model: dict[str, dict[str, Any]],
    name_field: str,
) -> None:
    """
    Write ``out_dir/models/<role>/predictions.jsonl`` and ``summary.json`` for each key in
    ``summary_by_model`` (e.g. ``finetune`` / ``base`` from endpoint names).
    """
    if not summary_by_model:
        return
    models_root = out_dir / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    for role in summary_by_model:
        safe = _sanitize_filename(role) or "model"
        sub = models_root / safe
        sub.mkdir(parents=True, exist_ok=True)
        rows = [r for r in results if r.get(name_field) == role]
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        (sub / "predictions.jsonl").write_text(body + ("\n" if body else ""), encoding="utf-8")
        (sub / "summary.json").write_text(
            json.dumps(summary_by_model[role], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class EvalTarget:
    target_id: str
    name: str
    lat: float
    lon: float
    zoom: int
    category: str
    notes: str
    # Visual concept groups only. At least one token from each group should appear.
    expected_any: tuple[tuple[str, ...], ...]
    # Penalize if these false visual claims appear.
    forbidden_any: tuple[str, ...] = ()
    # Flag over-specific geography/protected-area claims that are not visually observable.
    claim_risk_any: tuple[str, ...] = ()
    min_words: int = 18
    visual_difficulty: str = "medium"


@dataclass
class TargetResult:
    target_id: str
    endpoint_name: str
    endpoint_url: str
    caption: str
    score: float
    expected_groups_total: int
    expected_groups_hit: int
    expected_hits: list[str] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)
    claim_risk_hits: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    word_count: int = 0
    passed: bool = False
    image_path: str = ""
    image_sha256: str = ""
    model_id: str = ""
    pipeline: str = ""
    error: str | None = None


@dataclass(frozen=True)
class InferenceResponse:
    caption: str
    model_id: str = ""
    pipeline: str = ""


def default_patagonia_targets() -> list[EvalTarget]:
    """
    Curated Patagonia evaluation set.

    Includes:
    - Los Alerces investigation anchor
    - Marine reserves in Patagonia / southern Argentine sea
    - Additional controls for glacial, fjord, port, and inland Andean contexts
    """
    return [
        EvalTarget(
            target_id="pat_los_alerces_np",
            name="Los Alerces National Park",
            lat=-42.8075,
            lon=-71.8989,
            zoom=10,
            category="andean_forest_lake",
            notes="Primary Patagonia anchor (temperate forest + glacial lakes).",
            expected_any=(
                ("lake", "lago", "water"),
                ("forest", "trees", "woodland"),
                ("mountain", "andes", "ridge", "valley"),
            ),
            claim_risk_any=("los alerces", "national park", "unesco", "chubut", "argentina"),
            visual_difficulty="medium",
        ),
        EvalTarget(
            target_id="pat_nahuel_huapi",
            name="Nahuel Huapi Region",
            lat=-41.08,
            lon=-71.50,
            zoom=10,
            category="andean_forest_lake",
            notes="Secondary Andean lake-forest control in northern Patagonia.",
            expected_any=(
                ("lake", "water"),
                ("forest", "trees"),
                ("mountain", "ridge", "andes"),
            ),
            claim_risk_any=("nahuel huapi", "bariloche", "argentina"),
            visual_difficulty="medium",
        ),
        EvalTarget(
            target_id="pat_perito_moreno_glacier",
            name="Perito Moreno Glacier",
            lat=-50.496,
            lon=-73.139,
            zoom=11,
            category="glacier_ice",
            notes="Cryosphere control for ice/glacier language.",
            expected_any=(
                ("glacier", "ice", "snow"),
                ("mountain", "valley", "ridge"),
            ),
            forbidden_any=("desert",),
            claim_risk_any=("perito moreno", "los glaciares", "argentina"),
            visual_difficulty="medium",
        ),
        # Marine reserves (explicit request)
        EvalTarget(
            target_id="pat_yaganes_mpa",
            name="Yaganes Marine Protected Area (center)",
            lat=-56.9330,
            lon=-65.4582,
            zoom=7,
            category="marine_reserve",
            notes=(
                "Southern Tierra del Fuego marine protected area. "
                "The protected-area label is not visually observable, so score only open-water context."
            ),
            expected_any=(
                ("ocean", "sea", "water", "marine", "open water"),
            ),
            claim_risk_any=("yaganes", "protected area", "marine reserve", "national park", "argentina"),
            min_words=10,
            visual_difficulty="hard_uniform_water",
        ),
        EvalTarget(
            target_id="pat_yaganes_nearshore_channel",
            name="Yaganes northern approach / Tierra del Fuego coast",
            lat=-55.55,
            lon=-66.25,
            zoom=8,
            category="marine_reserve_nearshore_control",
            notes=(
                "Nearshore visual control for the Yaganes evaluation area; evaluates coast/island/channel reading "
                "without requiring the model to identify the legal MPA."
            ),
            expected_any=(
                ("ocean", "sea", "water"),
                ("coast", "island", "channel", "strait"),
            ),
            claim_risk_any=("yaganes", "protected area", "marine reserve", "national park", "argentina", "chile"),
            visual_difficulty="medium",
        ),
        EvalTarget(
            target_id="pat_namuncura_burdwood",
            name="Namuncura - Banco Burdwood (center)",
            lat=-54.35,
            lon=-60.60,
            zoom=6,
            category="marine_reserve_offshore",
            notes=(
                "Offshore submarine-bank marine protected area. Satellite visible evidence is mostly open ocean; "
                "do not require the VLM to infer a reserve or seabed feature."
            ),
            expected_any=(
                ("ocean", "sea", "water", "marine", "open water"),
            ),
            claim_risk_any=("namuncura", "namuncurá", "burdwood", "banco", "protected area", "marine reserve"),
            min_words=10,
            visual_difficulty="hard_uniform_water",
        ),
        EvalTarget(
            target_id="pat_patagonia_austral_marine_park",
            name="Patagonia Austral Coastal Marine Park",
            lat=-45.07224,
            lon=-66.09692,
            zoom=9,
            category="marine_reserve_coastal",
            notes="Interjurisdictional coastal marine protected area (Chubut).",
            expected_any=(
                ("coast", "shore", "coastal"),
                ("ocean", "sea", "water"),
            ),
            claim_risk_any=("patagonia austral", "marine park", "protected area", "national park", "chubut", "argentina"),
            visual_difficulty="medium",
        ),
        # Additional suitable targets for broader evaluations
        EvalTarget(
            target_id="pat_puerto_madryn_port",
            name="Puerto Madryn Port",
            lat=-42.769,
            lon=-65.038,
            zoom=12,
            category="urban_coastal_control",
            notes="Anthropogenic coastal control (port/infrastructure).",
            expected_any=(
                ("port", "harbor", "terminal"),
                ("urban", "roads", "buildings", "infrastructure"),
                ("coast", "shore", "water"),
            ),
            claim_risk_any=("puerto madryn", "argentina", "chubut"),
            visual_difficulty="easy",
        ),
        EvalTarget(
            target_id="pat_strait_magellan",
            name="Strait of Magellan sector",
            lat=-52.95,
            lon=-70.85,
            zoom=8,
            category="maritime_chokepoint_control",
            notes="Maritime strait control for ocean-channel interpretation.",
            expected_any=(
                ("water", "sea", "ocean"),
                ("channel", "strait", "coast", "island"),
            ),
            claim_risk_any=("magellan", "magallanes", "argentina", "chile"),
            visual_difficulty="medium",
        ),
        EvalTarget(
            target_id="pat_torres_del_paine_fjords",
            name="Torres del Paine / fjord transition",
            lat=-51.15,
            lon=-73.00,
            zoom=9,
            category="fjord_mountain_control",
            notes="Fjord + mountain + glacial transition control.",
            expected_any=(
                ("mountain", "ridge", "valley"),
                ("water", "lake", "fjord"),
            ),
            claim_risk_any=("torres del paine", "chile", "national park"),
            visual_difficulty="medium",
        ),
    ]


def _sanitize_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def resolve_local_vlm_comparison_runs(cli_local_models: list[str]) -> list[tuple[str, str]]:
    """
    Local TiM-in-prompt VLM runs as ``(model_name, hf_model_id)``.

    If ``cli_local_models`` is non-empty, each entry is ``(sanitize(id), id)``.
    If empty, returns **finetune** and **base** from ``patagonia_comparison_hf_model_ids()`` (default comparison).
    """
    if cli_local_models:
        return [(_sanitize_filename(mid) or "model", mid.strip()) for mid in cli_local_models if mid.strip()]
    ids = patagonia_comparison_hf_model_ids()
    return [("finetune", ids["finetune"]), ("base", ids["base"])]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _match_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    """
    Match terms as words/phrases, not raw substrings.

    This avoids rewarding `sea` inside `season` or `port` inside `important`.
    """
    hits: list[str] = []
    for term in terms:
        raw = term.strip().lower()
        if not raw:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(raw).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        if re.search(pattern, text):
            hits.append(term)
    return hits


def _response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:300]
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=True)[:500]


def _mapbox_static_png(
    client: httpx.Client,
    *,
    token: str,
    lat: float,
    lon: float,
    zoom: int,
    size: int,
) -> bytes:
    wh = f"{size}x{size}"
    url = f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon},{lat},{zoom},0,0/{wh}"
    r = client.get(url, params={"access_token": token})
    if r.status_code >= 400:
        raise RuntimeError(f"Mapbox HTTP {r.status_code}: {_response_error_detail(r)}")
    ctype = r.headers.get("content-type", "").lower()
    if "image/" not in ctype:
        raise RuntimeError(f"Mapbox returned non-image content-type {ctype or '<missing>'}: {r.text[:200]}")
    return r.content


def _patagonia_still_cache_basename(t: EvalTarget, pixel_size: int, still_source: str) -> str:
    if still_source == "mapbox":
        return _sanitize_filename(f"{t.target_id}_z{t.zoom}_s{pixel_size}_{t.lat:.4f}_{t.lon:.4f}.png")
    return _sanitize_filename(f"{t.target_id}_stac_s{pixel_size}_{t.lat:.4f}_{t.lon:.4f}.png")


def patagonia_still_png_bytes(
    client: httpx.Client,
    *,
    target: EvalTarget,
    pixel_size: int,
    still_source: str,
    mapbox_token: str,
    stac_url: str,
    stac_collection: str,
    stac_bbox_half_km: float | None,
    stac_max_cloud: float | None,
    stac_max_items: int | None,
    stac_datetime: str,
) -> tuple[bytes, dict[str, Any]]:
    """
    RGB PNG bytes for one Patagonia eval target + small provenance dict (STAC item meta when applicable).
    """
    prov: dict[str, Any] = {"still_source": still_source}
    if still_source == "mapbox":
        raw = _mapbox_static_png(
            client,
            token=mapbox_token,
            lat=target.lat,
            lon=target.lon,
            zoom=target.zoom,
            size=pixel_size,
        )
        return raw, prov
    if still_source == "stac":
        from stac_reference_still import fetch_sentinel_reference_still

        dt_arg = stac_datetime.strip()
        im, st_meta = fetch_sentinel_reference_still(
            target.lat,
            target.lon,
            width_px=pixel_size,
            height_px=pixel_size,
            stac_url=stac_url.strip() or None,
            collection=stac_collection.strip() or None,
            bbox_half_km=stac_bbox_half_km,
            max_cloud=stac_max_cloud,
            max_items=stac_max_items,
            datetime_range=dt_arg or None,
        )
        buf = BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        prov.update(st_meta)
        return buf.getvalue(), prov

    raise ValueError(f"Unknown --still-source {still_source!r} (expected mapbox or stac)")


def write_patagonia_eval_still(
    *,
    client: httpx.Client,
    cache_dir: Path,
    target: EvalTarget,
    pixel_size: int,
    refresh: bool,
    still_source: str,
    mapbox_token: str,
    stac_url: str,
    stac_collection: str,
    stac_bbox_half_km: float | None,
    stac_max_cloud: float | None,
    stac_max_items: int | None,
    stac_datetime: str,
) -> tuple[Path, bytes, dict[str, Any]]:
    """Write or reuse a cached PNG; returns path, bytes, provenance."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    img_name = _patagonia_still_cache_basename(target, pixel_size, still_source)
    img_path = cache_dir / img_name
    if img_path.is_file() and img_path.stat().st_size > 0 and not refresh:
        return img_path, img_path.read_bytes(), {"still_source": still_source, "cached": True}
    image_bytes, prov = patagonia_still_png_bytes(
        client,
        target=target,
        pixel_size=pixel_size,
        still_source=still_source,
        mapbox_token=mapbox_token,
        stac_url=stac_url,
        stac_collection=stac_collection,
        stac_bbox_half_km=stac_bbox_half_km,
        stac_max_cloud=stac_max_cloud,
        stac_max_items=stac_max_items,
        stac_datetime=stac_datetime,
    )
    prov["cached"] = False
    img_path.write_bytes(image_bytes)
    return img_path, image_bytes, prov


def _infer_caption(
    client: httpx.Client,
    *,
    endpoint_url: str,
    image_bytes: bytes,
    ranked_clue_safe: bool,
) -> InferenceResponse:
    base = endpoint_url.rstrip("/")
    url = base if base.endswith("/v1/infer") else f"{base}/v1/infer"
    body = {
        "task": "caption",
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "ranked_clue_safe": ranked_clue_safe,
        "prompt_template_version": "satellite-v1",
    }
    r = client.post(url, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"VLM HTTP {r.status_code}: {_response_error_detail(r)}")
    payload = r.json()
    cap = str(payload.get("caption") or "").strip()
    if not cap:
        raise RuntimeError(f"Empty caption from {url}")
    return InferenceResponse(
        caption=cap,
        model_id=str(payload.get("model_id") or ""),
        pipeline=str(payload.get("pipeline") or ""),
    )


def _score_caption(
    caption: str,
    target: EvalTarget,
    threshold: float,
) -> tuple[float, int, int, list[str], list[str], list[str], list[str], int, bool]:
    text = caption.lower()
    expected_hits: list[str] = []
    quality_flags: list[str] = []
    groups_hit = 0
    for idx, group in enumerate(target.expected_any, start=1):
        group_hits = _match_terms(text, group)
        if group_hits:
            groups_hit += 1
            expected_hits.append(group_hits[0])
        else:
            quality_flags.append(f"missing_visual_group_{idx}")
    forbidden_hits = _match_terms(text, target.forbidden_any)
    claim_risk_hits = _match_terms(text, target.claim_risk_any)
    wc = len([w for w in re.split(r"\s+", caption.strip()) if w])
    if wc < target.min_words:
        quality_flags.append("short_caption")
    if forbidden_hits:
        quality_flags.append("forbidden_visual_claim")
    if claim_risk_hits:
        quality_flags.append("over_specific_place_or_protection_claim")
    if target.visual_difficulty.startswith("hard"):
        quality_flags.append(target.visual_difficulty)

    len_quality = min(1.0, wc / float(target.min_words)) if wc > 0 else 0.0
    concept_quality = groups_hit / max(1, len(target.expected_any))
    claim_safety = max(0.0, 1.0 - 0.25 * len(claim_risk_hits))
    penalty = 0.25 * len(forbidden_hits)
    score = max(0.0, min(1.0, 0.75 * concept_quality + 0.15 * len_quality + 0.10 * claim_safety - penalty))
    passed = score >= threshold
    return (
        score,
        groups_hit,
        len(target.expected_any),
        expected_hits,
        forbidden_hits,
        claim_risk_hits,
        quality_flags,
        wc,
        passed,
    )


def _parse_endpoints(values: list[str], default_endpoint: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not values:
        return [("default", default_endpoint)] if default_endpoint else []
    for v in values:
        raw = v.strip()
        if not raw:
            continue
        if "=" in raw:
            name, url = raw.split("=", 1)
            n = name.strip() or "endpoint"
            u = url.strip().rstrip("/")
            if u:
                out.append((n, u))
        else:
            out.append((_sanitize_filename(raw) or "endpoint", raw.rstrip("/")))
    if not out:
        if default_endpoint:
            out.append(("default", default_endpoint))
    return out


def _health_url_for_endpoint(endpoint_url: str) -> str:
    base = endpoint_url.rstrip("/")
    if base.endswith("/v1/infer"):
        base = base[: -len("/v1/infer")]
    return f"{base}/health"


def _check_endpoint_health(client: httpx.Client, endpoint_url: str) -> dict[str, Any]:
    url = _health_url_for_endpoint(endpoint_url)
    try:
        r = client.get(url)
    except httpx.HTTPError as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
    if r.status_code >= 400:
        return {"ok": False, "url": url, "http_status": r.status_code, "error": _response_error_detail(r)}
    try:
        payload = r.json()
    except ValueError:
        payload = {"text": r.text[:300]}
    return {"ok": True, "url": url, "http_status": r.status_code, "payload": payload}


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description="Evaluate satellite VLM captions on Patagonia-focused targets.")
    p.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help=(
            "VLM endpoint as URL or name=url (repeatable). If omitted: use "
            "NUTONIC_PATAGONIA_EVAL_FINETUNE_URL + NUTONIC_PATAGONIA_EVAL_BASE_URL for finetune vs base "
            "(NuTonic/lspace vs LiquidAI/LFM2.5-VL-450M), else NUTONIC_LFM_VL_SATELLITE_URL / REPO_ID."
        ),
    )
    p.add_argument(
        "--still-source",
        choices=("mapbox", "stac"),
        default="stac",
        help="Reference imagery: Sentinel-2 via Earth Search STAC (default), or Mapbox Satellite static API.",
    )
    p.add_argument("--mapbox-token", default=(os.environ.get("MAPBOX_ACCESS_TOKEN") or ""), help="Mapbox token when --still-source mapbox (env MAPBOX_ACCESS_TOKEN).")
    p.add_argument(
        "--mapbox-size",
        type=int,
        default=640,
        help="Square edge length in pixels for both Mapbox static tiles and STAC-derived thumbnails.",
    )
    p.add_argument(
        "--stac-still-url",
        default="",
        help="STAC API root when --still-source stac (default: Earth Search or NUTONIC_STAC_STILL_URL).",
    )
    p.add_argument(
        "--stac-still-collection",
        default="",
        help="STAC collection id (default: sentinel-2-l2a or NUTONIC_STAC_STILL_COLLECTION).",
    )
    p.add_argument("--stac-still-bbox-half-km", type=float, default=14.0, help="STAC search bbox half-extent in km.")
    p.add_argument("--stac-still-max-cloud", type=float, default=80.0, help="STAC eo:cloud_cover upper bound (strict <).")
    p.add_argument("--stac-still-max-items", type=int, default=30, help="Max STAC items to consider per target.")
    p.add_argument(
        "--stac-still-datetime",
        default="",
        help="STAC datetime range, e.g. 2025-11-01/2026-04-30 (default: wide window or NUTONIC_STAC_STILL_DATETIME).",
    )
    p.add_argument("--timeout", type=float, default=45.0, help="HTTP timeout seconds.")
    p.add_argument("--ranked-clue-safe", action="store_true", help="Use ranked-safe prompt mode in /v1/infer.")
    p.add_argument("--score-threshold", type=float, default=0.55, help="Pass threshold for per-target score.")
    p.add_argument("--category", action="append", default=[], help="Filter categories (repeatable).")
    p.add_argument("--target-id", action="append", default=[], help="Filter target ids (repeatable).")
    p.add_argument("--max-targets", type=int, default=0, help="Cap target count after filtering (0=all).")
    p.add_argument("--list-targets", action="store_true", help="Print targets and exit.")
    p.add_argument("--report-path", default="", help="Optional output report path (.json).")
    p.add_argument("--image-cache-dir", default=str(DEFAULT_IMAGE_CACHE_DIR), help="Directory to store fetched still images.")
    p.add_argument("--refresh-images", action="store_true", help="Re-fetch stills even if cached PNGs exist.")
    p.add_argument("--skip-health-check", action="store_true", help="Skip GET /health on VLM endpoints before inference.")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any endpoint call errors or any scored target fails threshold.")
    args = p.parse_args(argv)

    targets = default_patagonia_targets()
    if args.category:
        want = {c.strip().lower() for c in args.category if c.strip()}
        targets = [t for t in targets if t.category.lower() in want]
    if args.target_id:
        want_id = {tid.strip() for tid in args.target_id if tid.strip()}
        targets = [t for t in targets if t.target_id in want_id]
    if args.max_targets > 0:
        targets = targets[: args.max_targets]

    if args.list_targets:
        for t in targets:
            print(f"{t.target_id} | {t.category} | {t.lat:.5f},{t.lon:.5f} | {t.name}")
        return 0

    if not targets:
        raise SystemExit("No targets selected after filtering.")

    if args.still_source == "mapbox" and not args.mapbox_token.strip():
        raise SystemExit("MAPBOX_ACCESS_TOKEN is required for --still-source mapbox (or pass --mapbox-token).")

    endpoints = resolve_patagonia_eval_endpoints(args.endpoint)
    if not endpoints:
        raise SystemExit(
            "No endpoint configured. Pass --endpoint name=url (or URL), "
            "or set NUTONIC_PATAGONIA_EVAL_FINETUNE_URL + NUTONIC_PATAGONIA_EVAL_BASE_URL, "
            "or set NUTONIC_LFM_VL_SATELLITE_URL."
        )
    cache_dir = Path(args.image_cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    results: list[TargetResult] = []
    endpoint_health: dict[str, dict[str, Any]] = {}
    still_provenance: dict[str, Any] = {}
    with httpx.Client(timeout=httpx.Timeout(args.timeout), follow_redirects=True) as client:
        if not args.skip_health_check:
            endpoint_health = {ep_name: _check_endpoint_health(client, ep_url) for ep_name, ep_url in endpoints}

        for t in targets:
            img_path, image_bytes, st_prov = write_patagonia_eval_still(
                client=client,
                cache_dir=cache_dir,
                target=t,
                pixel_size=args.mapbox_size,
                refresh=bool(args.refresh_images),
                still_source=args.still_source,
                mapbox_token=args.mapbox_token.strip(),
                stac_url=args.stac_still_url,
                stac_collection=args.stac_still_collection,
                stac_bbox_half_km=args.stac_still_bbox_half_km,
                stac_max_cloud=args.stac_still_max_cloud,
                stac_max_items=args.stac_still_max_items,
                stac_datetime=args.stac_still_datetime,
            )
            still_provenance[t.target_id] = st_prov
            image_sha = _sha256_bytes(image_bytes)

            for ep_name, ep_url in endpoints:
                tr = TargetResult(
                    target_id=t.target_id,
                    endpoint_name=ep_name,
                    endpoint_url=ep_url,
                    caption="",
                    score=0.0,
                    expected_groups_total=len(t.expected_any),
                    expected_groups_hit=0,
                    image_path=str(img_path),
                    image_sha256=image_sha,
                )
                try:
                    infer = _infer_caption(
                        client,
                        endpoint_url=ep_url,
                        image_bytes=image_bytes,
                        ranked_clue_safe=bool(args.ranked_clue_safe),
                    )
                    score, gh, gt, e_hits, f_hits, c_hits, q_flags, wc, passed = _score_caption(
                        infer.caption,
                        t,
                        threshold=args.score_threshold,
                    )
                    tr.caption = infer.caption
                    tr.model_id = infer.model_id
                    tr.pipeline = infer.pipeline
                    tr.score = round(score, 4)
                    tr.expected_groups_hit = gh
                    tr.expected_groups_total = gt
                    tr.expected_hits = e_hits
                    tr.forbidden_hits = f_hits
                    tr.claim_risk_hits = c_hits
                    tr.quality_flags = q_flags
                    tr.word_count = wc
                    tr.passed = passed
                except Exception as exc:  # noqa: BLE001
                    tr.error = f"{type(exc).__name__}: {exc}"
                results.append(tr)

    by_endpoint: dict[str, dict[str, Any]] = {}
    for ep_name, ep_url in endpoints:
        subset = [r for r in results if r.endpoint_name == ep_name]
        ok = [r for r in subset if r.error is None]
        passed = [r for r in ok if r.passed]
        by_endpoint[ep_name] = {
            "endpoint_url": ep_url,
            "targets_total": len(subset),
            "targets_scored": len(ok),
            "targets_passed": len(passed),
            "pass_rate": (len(passed) / len(ok)) if ok else 0.0,
            "mean_score": (sum(r.score for r in ok) / len(ok)) if ok else 0.0,
            "errors": len([r for r in subset if r.error is not None]),
        }

    payload = {
        "meta": {
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "ranked_clue_safe": bool(args.ranked_clue_safe),
            "score_threshold": args.score_threshold,
            "still_source": args.still_source,
            "mapbox_size": args.mapbox_size,
            "stac_still": {
                "stac_still_url": args.stac_still_url,
                "stac_still_collection": args.stac_still_collection,
                "stac_still_bbox_half_km": args.stac_still_bbox_half_km,
                "stac_still_max_cloud": args.stac_still_max_cloud,
                "stac_still_max_items": args.stac_still_max_items,
                "stac_still_datetime": args.stac_still_datetime,
            },
            "still_provenance_by_target": still_provenance,
            "target_count": len(targets),
            "comparison_expectations": {
                "expected_hf_models": patagonia_comparison_hf_model_ids(),
                "notes": (
                    "Deploy one HF Space per listed URL; each Space should load the matching weights. "
                    "Response ``model_id`` should reflect the loaded checkpoint."
                ),
            },
            "endpoint_health": endpoint_health,
            "targets": [
                {
                    "target_id": t.target_id,
                    "name": t.name,
                    "category": t.category,
                    "lat": t.lat,
                    "lon": t.lon,
                    "zoom": t.zoom,
                    "notes": t.notes,
                    "visual_difficulty": t.visual_difficulty,
                    "expected_any": t.expected_any,
                    "forbidden_any": t.forbidden_any,
                    "claim_risk_any": t.claim_risk_any,
                }
                for t in targets
            ],
        },
        "summary_by_endpoint": by_endpoint,
        "results": [
            {
                "target_id": r.target_id,
                "endpoint_name": r.endpoint_name,
                "endpoint_url": r.endpoint_url,
                "score": r.score,
                "passed": r.passed,
                "expected_groups_hit": r.expected_groups_hit,
                "expected_groups_total": r.expected_groups_total,
                "expected_hits": r.expected_hits,
                "forbidden_hits": r.forbidden_hits,
                "claim_risk_hits": r.claim_risk_hits,
                "quality_flags": r.quality_flags,
                "word_count": r.word_count,
                "image_path": r.image_path,
                "image_sha256": r.image_sha256,
                "model_id": r.model_id,
                "pipeline": r.pipeline,
                "caption": r.caption,
                "error": r.error,
            }
            for r in results
        ],
    }

    if args.report_path:
        report_path = Path(args.report_path).resolve()
    else:
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = (DEFAULT_REPORT_DIR / f"patagonia_vlm_eval_{ts}.json").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Patagonia VLM evaluation complete. report={report_path}")
    for ep_name, summ in by_endpoint.items():
        print(
            f"- {ep_name}: pass={summ['targets_passed']}/{summ['targets_scored']} "
            f"errors={summ['errors']} mean_score={summ['mean_score']:.3f} "
            f"url={summ['endpoint_url']}"
        )

    if args.strict:
        has_errors = any(r.error is not None for r in results)
        has_failed_scored = any((r.error is None) and (not r.passed) for r in results)
        if has_errors or has_failed_scored:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

