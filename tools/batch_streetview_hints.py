#!/usr/bin/env python3
"""
Offline Street View hint batch: pano frames → LFM-VL captions → per-location JSON.

Normative: docs/scripts/SPEC-batch-streetview-hints.md
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urljoin

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = REPO_ROOT / "data" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from generate_ai_guess_fixture import iter_catalog_locations  # noqa: E402
from validate_hint_strings import validate_caption_text  # noqa: E402

EXIT_OK = 0
EXIT_HARD = 9
EXIT_USAGE = 2

# VLMs often slightly exceed 400 chars; keep a hard cap for manifest / client safety.
MAX_PACK_CAPTION = 480
MAX_NARRATIVE = 900


@dataclass
class BatchConfig:
    catalog_root: Path
    poi_root: Path
    pano_service_url: str
    lfm_vl_url: str
    content_version: str
    output_dir: Path | None
    poi_limit: int | None
    location_ids: frozenset[str] | None
    location_ids_file: Path | None
    shuffle_seed: int | None
    sv_screenshots_per_location: int
    lfm_max_frames_per_request: int
    satellite_caption_service_url: str | None
    still_index_path: Path | None
    useful_hints_dir: Path | None
    inject_useful_hint_tone: bool
    prompt_template_version: str
    enable_narrative_pass: bool
    narrative_service_url: str | None
    skip_streetview_hints: bool = False
    allow_partial: bool = False
    timeout_sec: float = 120.0
    ranked_clue_safe: bool = True


def _normalize_base(url: str) -> str:
    return url.rstrip("/") + "/"


def _chunk(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _load_still_index(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    locs = data.get("locations")
    if not isinstance(locs, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in locs:
        if isinstance(row, dict) and row.get("location_id") is not None:
            out[str(row["location_id"])] = row
    return out


def _load_useful_hints(location_id: str, hints_dir: Path | None) -> dict[str, Any] | None:
    if hints_dir is None or not hints_dir.is_dir():
        return None
    p = hints_dir / f"{location_id}.json"
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(obj, dict) and isinstance(obj.get("useful_hints"), dict):
        return dict(obj["useful_hints"])
    return None


def _select_locations(cfg: BatchConfig) -> list[dict[str, Any]]:
    rows = iter_catalog_locations(cfg.catalog_root)
    if cfg.location_ids is not None:
        rows = [r for r in rows if r["location_id"] in cfg.location_ids]
    if cfg.location_ids_file is not None:
        raw = cfg.location_ids_file.read_text(encoding="utf-8")
        allow = {ln.strip() for ln in raw.splitlines() if ln.strip()}
        rows = [r for r in rows if r["location_id"] in allow]
    rows.sort(key=lambda r: r["location_id"])
    if cfg.shuffle_seed is not None:
        rng = random.Random(cfg.shuffle_seed)
        rng.shuffle(rows)
    if cfg.poi_limit is not None and cfg.poi_limit >= 0:
        rows = rows[: cfg.poi_limit]
    return rows


def _pano_sample(
    client: httpx.Client,
    pano_base: str,
    *,
    lat: float,
    lon: float,
    count: int,
) -> dict[str, Any]:
    base = _normalize_base(pano_base)
    body = {
        "request_id": str(uuid.uuid4()),
        "center": {"lat": lat, "lon": lon},
        "count": count,
        "radius_m": 120,
        "heading_mode": "RADIAL_OR_RANDOM",
        "image_width": 640,
        "image_height": 640,
    }
    primary = urljoin(base, "api/v1/panos/sample")
    legacy = urljoin(base, "v1/panos/sample")
    r1 = client.post(primary, json=body)
    if r1.status_code != 404:
        r1.raise_for_status()
        return r1.json()
    r2 = client.post(legacy, json=body)
    r2.raise_for_status()
    return r2.json()


def _lfm_suggestions(
    client: httpx.Client,
    lfm_base: str,
    frames: list[dict[str, Any]],
    *,
    ranked_safe: bool,
    prompt_version: str,
    useful_hints: dict[str, Any] | None,
    inject_tone: bool,
) -> list[dict[str, Any]]:
    url = urljoin(_normalize_base(lfm_base), "v1/suggestions/from_frames")
    payload: dict[str, Any] = {
        "frames": frames,
        "ranked_clue_safe": ranked_safe,
        "prompt_template_version": prompt_version,
    }
    if inject_tone and useful_hints:
        payload["useful_hints"] = useful_hints
    r = client.post(url, json=payload)
    r.raise_for_status()
    data = r.json()
    sug = data.get("suggestions")
    if not isinstance(sug, list):
        raise ValueError("LFM response missing suggestions[]")
    return [s for s in sug if isinstance(s, dict)]


def _validate_pack_suggestions(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in raw:
        text = str(s.get("text", "")).strip()
        vid = str(s.get("viewpoint_id", "decoy"))
        rank = int(s.get("rank", len(out) + 1))
        viol = validate_caption_text(text, max_len=MAX_PACK_CAPTION, path="streetview_hint_pack.text")
        if viol:
            raise ValueError("; ".join(v.format_line() for v in viol))
        out.append({"text": text, "viewpoint_id": vid, "rank": rank})
    out.sort(key=lambda x: (x["rank"], x["viewpoint_id"]))
    return out


def _optional_narrative(
    client: httpx.Client,
    url: str,
    pack: list[dict[str, Any]],
) -> str | None:
    if not url:
        return None
    endpoint = url.rstrip("/") + "/v1/narrative/fuse"
    body = {
        "captions": [{"viewpoint_id": p["viewpoint_id"], "text": p["text"]} for p in pack],
        "mission_flavor": "neutral",
    }
    try:
        r = client.post(endpoint, json=body, timeout=60.0)
        if r.status_code >= 400:
            return None
        data = r.json()
        text = data.get("narrative") or data.get("text")
        if not isinstance(text, str):
            return None
        text = text.strip()
        viol = validate_caption_text(text, max_len=MAX_NARRATIVE, path="streetview_assist_narrative")
        if viol:
            return None
        return text
    except httpx.HTTPError:
        return None


def _optional_satellite(
    client: httpx.Client,
    base: str,
    *,
    image_base64: str,
) -> dict[str, Any] | None:
    endpoint = base.rstrip("/") + "/v1/infer"
    try:
        r = client.post(
            endpoint,
            json={"task": "caption", "image_base64": image_base64},
            timeout=120.0,
        )
        if r.status_code >= 400:
            return None
        return r.json()
    except httpx.HTTPError:
        return None


def _get_health_json(client: httpx.Client, base: str) -> dict[str, Any]:
    r = client.get(urljoin(_normalize_base(base), "health"), timeout=10.0)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def _try_health_json(client: httpx.Client, base: str) -> dict[str, Any]:
    try:
        r = client.get(urljoin(_normalize_base(base), "health"), timeout=10.0)
        if r.status_code >= 400:
            return {}
        data = r.json()
        return data if isinstance(data, dict) else {}
    except httpx.HTTPError:
        return {}


def _pano_model_pin(pano_health: dict[str, Any]) -> dict[str, Any]:
    prov = str(pano_health.get("streetview_provider", "stub"))
    gcfg = str(pano_health.get("google_configured", "no"))
    uses_real_google = prov == "google" or (prov == "auto" and gcfg == "yes")
    pin: dict[str, Any] = {
        "api": "api/v1/panos/sample",
        "streetview_provider": prov,
        "google_configured": gcfg,
        "stub_jpeg": not uses_real_google,
    }
    return pin


def _lfm_model_pin(lfm_health: dict[str, Any], *, prompt_template_version: str) -> dict[str, Any]:
    backend = str(lfm_health.get("lfm_backend", "stub"))
    pin: dict[str, Any] = {
        "prompt_template_version": prompt_template_version,
        "lfm_backend": backend,
        "lfm_backend_config": lfm_health.get("lfm_backend_config"),
        "model_id": lfm_health.get("model_id"),
        "stub": backend == "stub",
    }
    if "openai_base_url" in lfm_health:
        pin["openai_base_url"] = lfm_health["openai_base_url"]
    return pin


def _satellite_service_pin(sat_health: dict[str, Any]) -> dict[str, Any] | None:
    if not sat_health:
        return None
    return {
        "api": "v1/infer",
        "lfm_satellite_backend": sat_health.get("lfm_satellite_backend"),
        "lfm_satellite_backend_config": sat_health.get("lfm_satellite_backend_config"),
        "model_id": sat_health.get("model_id"),
    }


def run_batch(cfg: BatchConfig, client: httpx.Client) -> int:
    if cfg.skip_streetview_hints:
        return EXIT_OK

    pano_base = _normalize_base(cfg.pano_service_url)
    lfm_base = _normalize_base(cfg.lfm_vl_url)
    pano_health: dict[str, Any] = {}
    lfm_health: dict[str, Any] = {}
    for label, base, slot in (
        ("pano", pano_base, "pano"),
        ("lfm", lfm_base, "lfm"),
    ):
        try:
            j = _get_health_json(client, base)
            if slot == "pano":
                pano_health = j
            else:
                lfm_health = j
        except httpx.HTTPError as e:
            print(f"{label} service health check failed ({base}health): {e}", file=sys.stderr)
            return EXIT_HARD

    sat_health: dict[str, Any] = {}
    sat_pin: dict[str, Any] | None = None
    if cfg.satellite_caption_service_url:
        sat_health = _try_health_json(client, cfg.satellite_caption_service_url)
        sat_pin = _satellite_service_pin(sat_health)

    out_root = cfg.output_dir or (REPO_ROOT / "data" / "cache" / cfg.content_version)
    sv_dir = out_root / "streetview"
    rep_dir = out_root / "reports"
    sv_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    still_by_loc: dict[str, dict[str, Any]] = {}
    if cfg.still_index_path and cfg.still_index_path.is_file():
        still_by_loc = _load_still_index(cfg.still_index_path)

    failures: list[dict[str, Any]] = []
    locations = _select_locations(cfg)
    if not locations:
        print("No catalog locations selected.", file=sys.stderr)
        return EXIT_USAGE

    for row in locations:
        lid = str(row["location_id"])
        lat = float(row["truth_lat"])
        lon = float(row["truth_lon"])
        try:
            pano_json = _pano_sample(
                client,
                pano_base,
                lat=lat,
                lon=lon,
                count=cfg.sv_screenshots_per_location,
            )
            frames_raw = pano_json.get("frames")
            if not isinstance(frames_raw, list) or not frames_raw:
                raise ValueError("pano service returned no frames")
            frames_api: list[dict[str, Any]] = []
            for fr in frames_raw:
                if not isinstance(fr, dict):
                    continue
                frames_api.append(
                    {
                        "image_base64": str(fr["image_base64"]),
                        "pano_id": fr.get("pano_id"),
                        "heading_deg": fr.get("heading_deg"),
                        "pitch_deg": fr.get("pitch_deg", 0.0),
                    }
                )
            useful = _load_useful_hints(lid, cfg.useful_hints_dir) if cfg.inject_useful_hint_tone else None
            merged_suggestions: list[dict[str, Any]] = []
            max_chunk = max(1, cfg.lfm_max_frames_per_request)
            for chunk in _chunk(frames_api, max_chunk):
                part = _lfm_suggestions(
                    client,
                    lfm_base,
                    chunk,
                    ranked_safe=cfg.ranked_clue_safe,
                    prompt_version=cfg.prompt_template_version,
                    useful_hints=useful,
                    inject_tone=cfg.inject_useful_hint_tone,
                )
                merged_suggestions.extend(part)
            pack = _validate_pack_suggestions(merged_suggestions)

            narrative: str | None = None
            if cfg.enable_narrative_pass and cfg.narrative_service_url:
                narrative = _optional_narrative(client, cfg.narrative_service_url, pack)

            satellite_side: dict[str, Any] | None = None
            if cfg.satellite_caption_service_url and lid in still_by_loc:
                still_rec = still_by_loc[lid]
                rel = still_rec.get("still_bundled_resource") or still_rec.get("still_path")
                if isinstance(rel, str) and rel:
                    img_path = REPO_ROOT / rel.replace("/", Path.sep) if not Path(rel).is_absolute() else Path(rel)
                    if img_path.is_file():
                        b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
                        sat = _optional_satellite(
                            client,
                            cfg.satellite_caption_service_url,
                            image_base64=b64,
                        )
                        if isinstance(sat, dict):
                            cap = sat.get("caption")
                            satellite_side = {
                                "pipeline": str(sat.get("pipeline") or "satellite_lfm_vl_specialist"),
                                "caption": str(cap).strip() if cap is not None else "",
                                "model_id": str(sat.get("model_id", "") or ""),
                            }
                            if not satellite_side["caption"]:
                                satellite_side["raw"] = sat

            model_pins: dict[str, Any] = {
                "streetview_pano_service": _pano_model_pin(pano_health),
                "lfm_vl_hint_service": _lfm_model_pin(lfm_health, prompt_template_version=cfg.prompt_template_version),
            }
            if sat_pin is not None:
                model_pins["lfm_vl_satellite_caption_service"] = sat_pin

            out_doc = {
                "location_id": lid,
                "streetview_hint_pack": pack,
                "streetview_assist_narrative": narrative,
                "model_pins": model_pins,
            }
            if satellite_side is not None:
                out_doc["satellite_caption_sidecar"] = satellite_side

            out_path = sv_dir / f"{lid}.json"
            out_path.write_text(json.dumps(out_doc, indent=2), encoding="utf-8")
            print(f"Wrote {out_path.relative_to(REPO_ROOT)}")
        except Exception as e:  # noqa: BLE001 — batch driver aggregates per-POI errors
            failures.append({"location_id": lid, "error": str(e), "type": type(e).__name__})
            print(f"[fail] {lid}: {e}", file=sys.stderr)
            if not cfg.allow_partial:
                rep_dir.joinpath("streetview_failures.json").write_text(
                    json.dumps(failures, indent=2),
                    encoding="utf-8",
                )
                return EXIT_HARD

    rep_dir.joinpath("streetview_failures.json").write_text(
        json.dumps(failures, indent=2),
        encoding="utf-8",
    )
    if failures and not cfg.allow_partial:
        return EXIT_HARD
    return EXIT_OK


def _build_client(timeout: float) -> Callable[[], httpx.Client]:
    def _factory() -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(timeout))

    return _factory


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch Street View hints via pano + LFM-VL HTTP services.")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--poi-root", type=Path, default=REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12")
    p.add_argument("--pano-service-url", type=str, required=False, default="http://127.0.0.1:7861")
    p.add_argument("--lfm-vl-url", type=str, required=False, default=None)
    p.add_argument("--lfm-service-url", type=str, default=None, help="Alias for --lfm-vl-url")
    p.add_argument("--content-version", type=str, default="dev-streetview")
    p.add_argument("--output-dir", type=Path, default=None, help="Default: data/cache/<content-version>")
    p.add_argument("--poi-limit", type=int, default=None)
    p.add_argument("--location-ids", type=str, default=None, help="Comma-separated location_id values")
    p.add_argument("--location-ids-file", type=Path, default=None)
    p.add_argument("--shuffle-seed", type=int, default=None)
    p.add_argument("--sv-screenshots-per-location", "--frame-count", type=int, default=6, dest="frame_count")
    p.add_argument("--lfm-max-frames-per-request", type=int, default=6)
    p.add_argument("--satellite-caption-service-url", type=str, default=None)
    p.add_argument("--still-index", type=Path, default=None)
    p.add_argument("--useful-hints-dir", type=Path, default=None)
    p.add_argument(
        "--inject-useful-hint-tone",
        action="store_true",
        help="Pass useful_hints into LFM body (default off; can anchor VLMs).",
    )
    p.add_argument("--prompt-template-version", type=str, default="stub-v1")
    p.add_argument("--enable-narrative-pass", action="store_true")
    p.add_argument("--narrative-service-url", type=str, default=None)
    p.add_argument("--skip-streetview-hints", action="store_true")
    p.add_argument("--allow-partial", action="store_true")
    p.add_argument("--timeout-sec", type=float, default=120.0)
    p.add_argument("--unsafe-ranked-clue-safe-off", action="store_true", help="Set ranked_clue_safe=false (lab only).")
    args = p.parse_args(argv)

    lfm_url = args.lfm_vl_url or args.lfm_service_url
    if not args.skip_streetview_hints and not lfm_url:
        print("Either --lfm-vl-url/--lfm-service-url or --skip-streetview-hints is required.", file=sys.stderr)
        return EXIT_USAGE

    loc_ids: frozenset[str] | None = None
    if args.location_ids:
        loc_ids = frozenset(x.strip() for x in args.location_ids.split(",") if x.strip())

    cfg = BatchConfig(
        catalog_root=args.catalog_root.resolve(),
        poi_root=args.poi_root.resolve(),
        pano_service_url=args.pano_service_url,
        lfm_vl_url=(lfm_url or "http://127.0.0.1:7862"),
        content_version=args.content_version,
        output_dir=args.output_dir.resolve() if args.output_dir else None,
        poi_limit=args.poi_limit,
        location_ids=loc_ids,
        location_ids_file=args.location_ids_file.resolve() if args.location_ids_file else None,
        shuffle_seed=args.shuffle_seed,
        sv_screenshots_per_location=args.frame_count,
        lfm_max_frames_per_request=args.lfm_max_frames_per_request,
        satellite_caption_service_url=args.satellite_caption_service_url,
        still_index_path=args.still_index.resolve() if args.still_index else None,
        useful_hints_dir=args.useful_hints_dir.resolve() if args.useful_hints_dir else None,
        inject_useful_hint_tone=args.inject_useful_hint_tone,
        prompt_template_version=args.prompt_template_version,
        enable_narrative_pass=args.enable_narrative_pass,
        narrative_service_url=args.narrative_service_url,
        skip_streetview_hints=args.skip_streetview_hints,
        allow_partial=args.allow_partial,
        timeout_sec=args.timeout_sec,
        ranked_clue_safe=not args.unsafe_ranked_clue_safe_off,
    )

    factory = _build_client(cfg.timeout_sec)
    with factory() as client:
        return run_batch(cfg, client)


if __name__ == "__main__":
    raise SystemExit(main())
