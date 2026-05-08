#!/usr/bin/env python3
"""Build VLM SFT JSONL where user turns pair multi-image materialization + capped TerraMind context."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_TIM_SRC = REPO_ROOT / "inference" / "terramind_tim_local" / "src"
if str(_TIM_SRC) not in sys.path:
    sys.path.insert(0, str(_TIM_SRC))

from nutonic_terramind_tim_local.tim_defaults import DEFAULT_TIM_MODEL_ID

from lfm_vl_sft_dataset.hf_upload import upload_dataset_folder
from lfm_vl_sft_dataset.jsonl_format import write_jsonl
from lfm_vl_sft_dataset.terramind_assessment_sft import (
    brief_fuse_post,
    build_assessment_row,
    cap_tim_context,
    decode_vlm_artifacts_to_files,
    lat_lon_from_materialize_bbox,
    load_seed_aois,
    materialize_post,
    merge_tim_into_context,
    remove_tim_coordinates_outside_manifest,
    run_manifest_excerpt_from_materialize,
    save_e2e_fixture_bundle,
    split_for_sample,
    summarize_tim_context_for_training,
    tim_infer_config_from_materialize,
    tim_infer_post,
    write_mapbox_rgb_as_jpeg_for_tim,
)

DEFAULT_HF_REPO = "NuTonic/terramind-assessment-sft-v1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tim_jsonl_for_map(path: Path, map_id: str | None, location_id: str | None) -> dict[str, Any]:
    first: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if first is None:
            first = obj
        if map_id and str(obj.get("map_id", "")) != map_id:
            continue
        if location_id and str(obj.get("location_id", "")) != location_id:
            continue
        return obj
    if first is not None:
        return first
    raise ValueError(f"No JSON lines in {path}")


def _resolve_materialize_dict(
    *,
    offline_fixture: Path | None,
    materialize_json: Path | None,
    materialize_url: str | None,
    mat_body: dict[str, Any],
) -> dict[str, Any]:
    if materialize_json is not None:
        return _load_json(materialize_json)
    if offline_fixture is not None:
        p = offline_fixture / "materialize.json"
        if not p.is_file():
            p = offline_fixture / "materialize_response.json"
        if not p.is_file():
            raise FileNotFoundError(f"Expected {offline_fixture / 'materialize.json'} (or materialize_response.json)")
        return _load_json(p)
    if materialize_url:
        return materialize_post(materialize_url, mat_body)
    raise ValueError("Provide one of: --offline-fixture, --materialize-json, or --materialize-url")


def _resolve_tim_context(
    *,
    offline_fixture: Path | None,
    tim_json: Path | None,
    tim_jsonl: Path | None,
    tim_url: str | None,
    tim_body: dict[str, Any] | None,
    map_id: str | None,
    location_id: str | None,
) -> dict[str, Any]:
    if tim_json is not None:
        return merge_tim_into_context(_load_json(tim_json))
    if offline_fixture is not None:
        tj = offline_fixture / "tim.json"
        if tj.is_file():
            return merge_tim_into_context(_load_json(tj))
        tjl = offline_fixture / "tim_export.jsonl"
        if tjl.is_file():
            return merge_tim_into_context(_load_tim_jsonl_for_map(tjl, map_id, location_id))
    if tim_jsonl is not None:
        return merge_tim_into_context(_load_tim_jsonl_for_map(Path(tim_jsonl), map_id, location_id))
    if tim_url and tim_body is not None:
        return merge_tim_into_context(tim_infer_post(tim_url, tim_body))
    raise ValueError("Provide TiM context via --offline-fixture (tim.json|tim_export.jsonl), --tim-json, --tim-jsonl, or --tim-url + tim config")


def _materialize_request_for_seed(seed: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    profile = str(seed.get("analysis_profile") or args.default_profile).strip()
    body: dict[str, Any] = {
        "latitude": float(seed["lat"]),
        "longitude": float(seed["lon"]),
        "bbox_half_km": float(args.bbox_half_km),
        "analysis_profile": profile,
        "vlm_contract_id": str(args.vlm_contract_id),
        "sentinel_fetch_mode": str(args.sentinel_fetch_mode),
        "enable_tim": bool(args.enable_tim_materialize),
        "tim_branch": str(args.tim_branch),
        "mapbox_zoom": int(args.mapbox_zoom),
        "max_cloud_cover": float(args.max_cloud_cover),
        "stac_url": str(args.stac_url),
        "collection_id": str(args.collection_id),
    }
    di = str(getattr(args, "datetime_interval", "") or "").strip()
    if di:
        body["datetime_interval"] = di
    return body


def main() -> int:
    p = argparse.ArgumentParser(description="Build TerraMind-conditioned VLM assessment SFT dataset.")
    p.add_argument(
        "--offline-fixture",
        type=Path,
        default=None,
        help="Directory with materialize.json (or materialize_response.json) and optional tim.json / tim_export.jsonl",
    )
    p.add_argument("--materialize-url", default="", help="Base URL for pro_materialization_service (live).")
    p.add_argument("--materialize-json", type=Path, default=None, help="Replay a saved MaterializeResult JSON (no HTTP).")
    p.add_argument("--tim-url", default="", help="Base URL for terramind_tim_local Space (live).")
    p.add_argument("--tim-json", type=Path, default=None, help="Replay saved TiM export JSON object.")
    p.add_argument("--tim-jsonl", type=Path, default=None, help="First matching or first line of TiM NDJSON export.")
    p.add_argument("--brief-fuse-url", default="", help="Optional lfm_vl_hint_service base URL for /v1/pro/brief/fuse.")
    p.add_argument(
        "--e2e",
        action="store_true",
        help="Shorthand live pipeline: requires --materialize-url and --tim-url (downloads per seed, STAC-aligned TiM).",
    )
    p.add_argument(
        "--allow-no-tim",
        action="store_true",
        help="Omit TiM context (empty JSON). Offline-friendly smoke without tim.json / tim_url.",
    )
    p.add_argument(
        "--download-fixture-dir",
        type=Path,
        default=None,
        help="After each successful live row, write materialize.json + tim.json under this directory (replay later with --offline-fixture).",
    )
    p.add_argument(
        "--datetime-interval",
        default="",
        help="Optional STAC window forwarded to materialize (e.g. 2024-04-01/2024-04-30). TiM infers the same window from materialize when live.",
    )

    p.add_argument(
        "--seed-aoi",
        type=Path,
        default=None,
        help="JSONL seeds: lat, lon, optional analysis_profile, map_id, location_id. "
        "Generate from GeoGuessr trees / HF / events via data/scripts/export_terramind_assessment_seed_aois.py.",
    )
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lon", type=float, default=None)
    p.add_argument("--default-profile", default="brief_only")
    p.add_argument("--map-id", default=None)
    p.add_argument("--location-id", default=None)

    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "downloads" / "terramind_assessment_sft")
    p.add_argument("--max-samples", type=int, default=10_000)
    p.add_argument("--bbox-half-km", type=float, default=5.0)
    p.add_argument(
        "--vlm-contract-id",
        default="nutonic.pro.vlm.v1_512_s2_only",
        help="Default: Sentinel-only false-color + cloud mask (no Mapbox). Use nutonic.pro.vlm.v1_512_fc_scl for Mapbox + S2.",
    )
    p.add_argument(
        "--sentinel-fetch-mode",
        default="TERRAMIND_SPECTRAL",
        help="Default TERRAMIND_SPECTRAL for Sentinel-backed contracts; use MINIMAL_RGB only for mapbox_rgb-only contracts.",
    )
    p.add_argument("--enable-tim-materialize", action="store_true", help="Request tim_payload from materialization.")
    p.add_argument(
        "--tim-branch",
        default="S2L2A_full",
        help="TiM export branch; default S2L2A_full for STAC-aligned spectral materialization.",
    )
    p.add_argument("--mapbox-zoom", type=int, default=12)
    p.add_argument("--max-cloud-cover", type=float, default=30.0)
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection-id", default="sentinel-2-l2a")

    p.add_argument("--tim-model-id", default=DEFAULT_TIM_MODEL_ID)
    p.add_argument("--tim-device", default="cpu")

    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--upload-repo", default=DEFAULT_HF_REPO)
    p.add_argument("--hf-token", default=None)
    p.add_argument("--private-repo", action="store_true")

    args = p.parse_args()
    offline_fixture: Path | None = args.offline_fixture
    mat_url = (args.materialize_url or "").strip() or None
    mat_json = args.materialize_json
    mat_sources = sum(1 for x in (offline_fixture, mat_json, mat_url) if x)
    if mat_sources != 1:
        print("Provide exactly one of: --offline-fixture, --materialize-json, or --materialize-url", file=sys.stderr)
        return 2

    if args.e2e:
        if not mat_url or not (args.tim_url or "").strip():
            print("--e2e requires non-empty --materialize-url and --tim-url", file=sys.stderr)
            return 2

    seeds: list[dict[str, Any]] = []
    if args.seed_aoi is not None:
        seeds = load_seed_aois(args.seed_aoi.resolve())
    elif args.lat is not None and args.lon is not None:
        seeds = [
            {
                "lat": float(args.lat),
                "lon": float(args.lon),
                "analysis_profile": args.default_profile,
                "map_id": args.map_id or "single_seed",
                "location_id": args.location_id or "single_seed",
            }
        ]
    elif offline_fixture is not None:
        seeds = [
            {
                "lat": 0.0,
                "lon": 0.0,
                "analysis_profile": args.default_profile,
                "map_id": args.map_id or "offline_fixture",
                "location_id": args.location_id or "offline_fixture",
            }
        ]
    elif mat_json is not None and not mat_url:
        mat0 = _load_json(mat_json.resolve())
        center = lat_lon_from_materialize_bbox(mat0)
        lat0, lon0 = (center if center is not None else (0.0, 0.0))
        seeds = [
            {
                "lat": lat0,
                "lon": lon0,
                "analysis_profile": args.default_profile,
                "map_id": args.map_id or "replay",
                "location_id": args.location_id or "replay",
            }
        ]
    else:
        print("Provide --seed-aoi or --lat/--lon when using --materialize-url.", file=sys.stderr)
        return 2

    tim_ok = bool(args.tim_json or args.tim_jsonl or (args.tim_url or "").strip())
    if offline_fixture is not None:
        d = offline_fixture
        tim_ok = tim_ok or (d / "tim.json").is_file() or (d / "tim_export.jsonl").is_file()
    if mat_json is not None and not mat_url and (args.tim_json is not None or args.tim_jsonl is not None):
        tim_ok = True
    if args.allow_no_tim:
        tim_ok = True
    if not tim_ok:
        print(
            "Provide TiM context via --tim-json, --tim-jsonl, --tim-url, or files under --offline-fixture "
            "(tim.json or tim_export.jsonl), or pass --allow-no-tim.",
            file=sys.stderr,
        )
        return 2

    out_dir = args.out_dir.resolve()
    images_dir = out_dir / "images"
    data_dir = out_dir / "data"
    meta_dir = out_dir / "metadata"
    images_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    n = 0
    for seed in seeds[: int(args.max_samples)]:
        mat_body = _materialize_request_for_seed(seed, args) if mat_url else {}

        try:
            mat = _resolve_materialize_dict(
                offline_fixture=offline_fixture.resolve() if offline_fixture else None,
                materialize_json=mat_json,
                materialize_url=mat_url,
                mat_body=mat_body,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] materialize failed: {exc}", file=sys.stderr)
            continue

        map_id = str(seed.get("map_id") or args.map_id or "unset_map")
        location_id = str(seed.get("location_id") or args.location_id or "unset_loc")
        profile = str(seed.get("analysis_profile") or mat_body.get("analysis_profile") or args.default_profile)
        stem = f"row_{n:05d}"

        tim_url = (args.tim_url or "").strip() or None
        effective_tim_branch = str(mat_body.get("tim_branch") or args.tim_branch)
        tim_api_snapshot: dict[str, Any] | None = None
        tim_raw: dict[str, Any]
        if args.allow_no_tim:
            tim_raw = {}
        elif tim_url:
            try:
                jpeg_path: str | None = None
                if effective_tim_branch == "RGB_mapbox" and str(args.sentinel_fetch_mode) == "MINIMAL_RGB":
                    p_jpeg = out_dir / ".cache" / "tim_rgb" / f"{stem}_mapbox.jpg"
                    if write_mapbox_rgb_as_jpeg_for_tim(mat, p_jpeg):
                        jpeg_path = str(p_jpeg.resolve())
                tim_body_live = tim_infer_config_from_materialize(
                    mat,
                    seed,
                    mat_body,
                    model_id=str(args.tim_model_id),
                    device=str(args.tim_device),
                    tim_branch=effective_tim_branch,
                    rgb_jpeg_path=jpeg_path,
                )
                tim_api_snapshot = tim_infer_post(tim_url, tim_body_live)
                tim_raw = merge_tim_into_context(tim_api_snapshot)
            except Exception as exc:  # noqa: BLE001
                print(f"[skip] tim context failed: {exc}", file=sys.stderr)
                continue
        else:
            try:
                tim_raw = _resolve_tim_context(
                    offline_fixture=offline_fixture.resolve() if offline_fixture else None,
                    tim_json=args.tim_json,
                    tim_jsonl=args.tim_jsonl,
                    tim_url=None,
                    tim_body=None,
                    map_id=map_id,
                    location_id=location_id,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[skip] tim context failed: {exc}", file=sys.stderr)
                continue

        rm_raw = run_manifest_excerpt_from_materialize(mat)
        tim_work: dict[str, Any] = dict(tim_raw) if isinstance(tim_raw, dict) else {}
        tim_work = remove_tim_coordinates_outside_manifest(tim_work, rm_raw)
        tim_summarized = summarize_tim_context_for_training(tim_work)
        tim_capped = cap_tim_context(tim_summarized)
        rm_excerpt = cap_tim_context(rm_raw)
        tim_branch = None
        tp = mat.get("tim_payload")
        if isinstance(tp, dict):
            tim_branch = str(tp.get("branch") or "") or None
        if tim_branch is None and tim_url:
            tim_branch = effective_tim_branch

        brief: dict[str, Any] | None = None
        if (args.brief_fuse_url or "").strip():
            try:
                brief = brief_fuse_post(
                    args.brief_fuse_url,
                    {
                        "profile": profile,
                        "tim_summary": tim_capped,
                        "artifact_refs": [{"artifact_id": a.get("role", "a"), "kind": "image"} for a in (mat.get("vlm_artifacts") or []) if isinstance(a, dict)],
                        "jobs": [],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] brief fuse skipped: {exc}", file=sys.stderr)

        sample_id = f"{map_id}_{location_id}_{profile}_{n:04d}"
        try:
            rel_imgs, canonical, img_roles = decode_vlm_artifacts_to_files(mat, images_dir, stem=stem)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] decode artifacts: {exc}", file=sys.stderr)
            continue

        if args.download_fixture_dir and tim_api_snapshot is not None:
            try:
                save_e2e_fixture_bundle(
                    (Path(args.download_fixture_dir).resolve() / stem),
                    materialize=mat,
                    tim_export=tim_api_snapshot,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] download-fixture-dir write failed: {exc}", file=sys.stderr)

        if offline_fixture:
            source_mode = "offline_fixture"
        elif mat_json and not mat_url:
            source_mode = "replay"
        elif mat_url and tim_url:
            source_mode = "e2e_live"
        else:
            source_mode = "live"

        row = build_assessment_row(
            sample_id=sample_id,
            image_rel_paths=rel_imgs,
            analysis_profile=profile,
            canonical_surface_id=canonical,
            tim_context=tim_capped,
            run_manifest_excerpt=rm_excerpt or None,
            brief_fuse=brief,
            tim_branch=tim_branch,
            source_mode=source_mode,
            image_roles=img_roles,
        )
        split = split_for_sample(sample_id)
        by_split[split].append(row)
        sidecar = {
            "sample_id": sample_id,
            "split": split,
            "map_id": map_id,
            "location_id": location_id,
            "analysis_profile": profile,
            "materialization_id": mat.get("materialization_id"),
            "cache_key": mat.get("cache_key"),
            "canonical_surface_id": canonical,
            "image_paths": rel_imgs,
            "image_roles": img_roles,
        }
        (meta_dir / f"{stem}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        n += 1

    for name in ("train", "validation", "test"):
        write_jsonl(data_dir / f"{name}.jsonl", by_split.get(name, []))

    readme = out_dir / "README.md"
    readme.write_text(
        "# TerraMind-conditioned assessment SFT\n\n"
        "Multi-image user turns: **raw** contract rasters (e.g. `sentinel_fc`, `cloud_mask_thumb`) plus any "
        "**profile overlay PNGs** from materialization, then capped TiM JSON in text.\n\n"
        "**Offline:** `--offline-fixture` with `materialize.json` + `tim.json` (or `tim_export.jsonl`), or "
        "`--materialize-json` + `--tim-json` / `--tim-jsonl` (no HTTP).\n\n"
        "**E2E live:** `--materialize-url` + `--tim-url` + `--seed-aoi` or `--lat`/`--lon` (optional `--e2e` guard); "
        "TiM uses **STAC-aligned** tensors from the same AOI/window as materialization. "
        "`--download-fixture-dir` saves `materialize.json` + `tim.json` per row for later offline replay.\n\n"
        "Assistant targets are deterministic rule text (teacher placeholder); replace with reviewed labels as needed.\n",
        encoding="utf-8",
    )
    print(
        f"Wrote rows total={n} train={len(by_split['train'])} val={len(by_split['validation'])} test={len(by_split['test'])} -> {data_dir}"
    )

    if not args.no_upload and n > 0:
        upload_dataset_folder(
            out_dir,
            args.upload_repo,
            private=args.private_repo,
            token=args.hf_token,
        )
        print(f"Uploaded to https://huggingface.co/datasets/{args.upload_repo}")

    return 0 if n else 2


if __name__ == "__main__":
    raise SystemExit(main())
