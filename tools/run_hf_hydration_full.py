#!/usr/bin/env python3
"""
Submit Hugging Face Jobs for full cache hydration (sequential):

1. **sv-lfm** — Street View + LFM-VL batch (GPU), uploads under ``runs/<content_version>/``.
2. **tim** — TerraMind TiM STAC batch (GPU), uploads ``runs/<content_version>/tim/``.
3. **llm-sidecars** — narrative batch (GPU + vLLM / transformers / optional Ollama), uploads ``runs/<content_version>/narrative/``.

Then optionally ``snapshot_download`` the output dataset locally. No model weights load on your laptop.

Environment (after loading ``.env``):
  ``HF_API_WRITE`` — submit Jobs + container uploads (falls back to ``HF_TOKEN``).
  ``HF_API_READ`` — used by the download step when set (else write token / ``HF_TOKEN``).
  ``NUTONIC_HYDRATION_SV_LFM_IMAGE``, ``NUTONIC_HYDRATION_TIM_IMAGE``, ``NUTONIC_HYDRATION_LLM_IMAGE``
  (or pass ``--sv-image``, ``--tim-image``, ``--llm-image``).
  ``NUTONIC_HYDRATION_OUTPUT_DATASET`` — Hub dataset id for uploads.
  ``GOOGLE_MAPS_API_KEY``, ``MAPBOX_ACCESS_TOKEN`` — Job **secrets** for ``sv-lfm`` only.

CLI ``--poi-limit N`` sets ``NUTONIC_POI_LIMIT`` for Jobs (single-tree ``geoguessr_poi_12`` slice; TiM uses
the matching bundled YAML when ``N`` is 5). Geo context uses ``--allow-partial`` in the sv-lfm Job by default;
use ``--skip-geo-hints`` to skip geo + useful_hints, or set ``NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL=0`` for strict failure.

Optional **Street View** flags (``--shuffle-seed``, ``--pano-sampling-mode``, …) are merged into the
**sv-lfm** Job environment only (see ``tools/hf_jobs/pano_batch_env.py``).

This script does not print secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_HFJ = REPO_ROOT / "tools" / "hf_jobs"
if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

from hf_hub_tokens import apply_hf_read_token, apply_hf_tokens_for_hub
import pano_batch_env  # noqa: E402
import inference_job_env  # noqa: E402
from submit_nutonic_hydration_job import _load_dotenv, submit_hydration_job

DEFAULT_TIM_CONFIG = (
    "/workspace/inference/terramind_tim_local/config.hf_job_geoguessr_poi12_first3.yaml"
)
DEFAULT_TIM_CONFIG_FIVE = (
    "/workspace/inference/terramind_tim_local/config.hf_job_geoguessr_poi12_first5.yaml"
)


def _collect_secrets_for_sv() -> dict[str, str]:
    secrets: dict[str, str] = {}
    tok = (os.environ.get("HF_API_WRITE") or os.environ.get("HF_TOKEN") or "").strip()
    if tok:
        secrets["HF_TOKEN"] = tok
    for key in (
        "GOOGLE_MAPS_API_KEY",
        "GOOGLE_STREETVIEW_API_KEY",
        "MAPBOX_ACCESS_TOKEN",
        "MAPBOX_TOKEN",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            secrets[key] = v
    return secrets


def _collect_secrets_for_tim_llm() -> dict[str, str]:
    secrets: dict[str, str] = {}
    tok = (os.environ.get("HF_API_WRITE") or os.environ.get("HF_TOKEN") or "").strip()
    if tok:
        secrets["HF_TOKEN"] = tok
    return secrets


def _wait_job(job_id: str, *, poll_sec: float, max_wait_sec: float) -> str:
    from huggingface_hub import HfApi

    api = HfApi()
    deadline = time.monotonic() + max_wait_sec
    last = ""
    while time.monotonic() < deadline:
        info = api.inspect_job(job_id=job_id)
        stage = str(info.status.stage)
        last = stage
        if stage == "COMPLETED":
            return "COMPLETED"
        if stage in ("ERROR", "CANCELED", "DELETED"):
            msg = info.status.message or ""
            raise RuntimeError(f"job {job_id} ended with stage={stage!r} message={msg!r}")
        time.sleep(poll_sec)
    raise TimeoutError(f"job {job_id} still running after {max_wait_sec}s (last stage {last!r})")


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        description="Run full HF Jobs hydration (sv-lfm + TiM + llm-sidecars) and download outputs.",
    )
    p.add_argument("--sv-image", default=os.environ.get("NUTONIC_HYDRATION_SV_LFM_IMAGE", "").strip())
    p.add_argument("--tim-image", default=os.environ.get("NUTONIC_HYDRATION_TIM_IMAGE", "").strip())
    p.add_argument("--llm-image", default=os.environ.get("NUTONIC_HYDRATION_LLM_IMAGE", "").strip())
    p.add_argument("--content-version", required=True)
    p.add_argument(
        "--output-dataset",
        default=os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "NuTonic/nutonic-hydration-cache").strip(),
    )
    p.add_argument("--sv-flavor", default=os.environ.get("NUTONIC_HYDRATION_SV_FLAVOR", "a10g_small"))
    p.add_argument("--tim-flavor", default=os.environ.get("NUTONIC_HYDRATION_TIM_FLAVOR", "a10g_small"))
    p.add_argument(
        "--llm-flavor",
        default=os.environ.get("NUTONIC_HYDRATION_LLM_FLAVOR", "t4-medium"),
        help="HF Job hardware for llm-sidecars (GPU recommended for vLLM / transformers).",
    )
    p.add_argument(
        "--tim-config-in-container",
        default=None,
        help="TiM YAML path inside the tim image (overrides NUTONIC_TIM_HF_CONFIG; default first5 when --poi-limit 5, else first3).",
    )
    p.add_argument(
        "--poi-limit",
        type=int,
        default=None,
        metavar="N",
        help="Limit to first N POIs from geoguessr_poi_12 (sets NUTONIC_POI_LIMIT for all Jobs).",
    )
    p.add_argument(
        "--skip-geo-hints",
        action="store_true",
        help="Set NUTONIC_SKIP_GEO_HINTS=1 for sv-lfm / llm (skips geo_context + useful_hints; still runs Mapbox stills + batch).",
    )
    p.add_argument(
        "--shuffle-seed",
        type=int,
        default=None,
        metavar="N",
        help="sv-lfm only: NUTONIC_SHUFFLE_SEED for catalog shuffle + per-POI pano jitter derivation.",
    )
    p.add_argument(
        "--pano-sampling-mode",
        type=str,
        default=None,
        help="sv-lfm only: e.g. STOCHASTIC_S2_FOOTPRINT (default in batch), LEGACY_RADIAL_OFFSET, OMNI_SINGLE_PANO.",
    )
    p.add_argument("--pano-jitter-seed", type=int, default=None, help="sv-lfm only: fixed --pano-jitter-seed for every POI.")
    p.add_argument("--pano-area-radius-m", type=float, default=None, help="sv-lfm only: disk radius override.")
    p.add_argument("--pano-min-anchor-separation-m", type=float, default=None, help="sv-lfm only: min anchor separation (m).")
    p.add_argument(
        "--pano-legacy-radius-m",
        type=float,
        default=None,
        help="sv-lfm only: radius_m when sampling mode is LEGACY_RADIAL_OFFSET.",
    )
    p.add_argument("--timeout", default=os.environ.get("NUTONIC_HYDRATION_JOB_TIMEOUT", "12h"))
    p.add_argument("--poll-seconds", type=float, default=45.0)
    p.add_argument("--max-wait-minutes", type=float, default=720.0)
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--skip-tim", action="store_true", help="Do not submit the TerraMind TiM GPU job.")
    p.add_argument("--dry-run-submit", action="store_true", help="Print job specs only (no submit / wait / download).")
    p.add_argument(
        "--narrative-llm-live",
        action="store_true",
        help="llm-sidecars Job only: set NUTONIC_NARRATIVE_LLM_LIVE=1 (in-process transformers narrative by default; see tools/hf_jobs/README.md).",
    )
    args = p.parse_args(argv)

    if not args.sv_image:
        print("Missing --sv-image or NUTONIC_HYDRATION_SV_LFM_IMAGE", file=sys.stderr)
        return 2
    if not args.skip_tim and not args.tim_image:
        print("Missing --tim-image or NUTONIC_HYDRATION_TIM_IMAGE (or pass --skip-tim)", file=sys.stderr)
        return 2
    llm_image = args.llm_image or args.sv_image

    env_common: dict[str, object] = {
        "CONTENT_VERSION": args.content_version,
        "NUTONIC_HYDRATION_OUTPUT_DATASET": args.output_dataset,
        "POIDATA_MOUNT": "/mnt/poidata",
    }
    if args.poi_limit is not None:
        if args.poi_limit < 1:
            print("--poi-limit must be >= 1", file=sys.stderr)
            return 2
        env_common["NUTONIC_POI_LIMIT"] = str(args.poi_limit)
    if args.skip_geo_hints:
        env_common["NUTONIC_SKIP_GEO_HINTS"] = "1"

    env_sv_lfm = {
        **env_common,
        **pano_batch_env.pano_sv_job_env_from_argparse(args),
        **inference_job_env.lfm_vl_hint_env_from_environ(),
        **inference_job_env.geo_pipeline_env_from_environ(),
    }
    env_llm = {
        **env_common,
        **({"NUTONIC_NARRATIVE_LLM_LIVE": "1"} if args.narrative_llm_live else {}),
        **inference_job_env.narrative_llm_job_env_from_environ(),
    }

    cli_tim = (args.tim_config_in_container or "").strip()
    env_tim = os.environ.get("NUTONIC_TIM_HF_CONFIG", "").strip()
    if cli_tim:
        tim_cfg = cli_tim
    elif env_tim:
        tim_cfg = env_tim
    elif args.poi_limit == 5:
        tim_cfg = DEFAULT_TIM_CONFIG_FIVE
    else:
        tim_cfg = DEFAULT_TIM_CONFIG

    sv_cmd = [
        "python",
        "/workspace/tools/hf_jobs/entrypoint_hf_hydration.py",
        "sv-lfm",
    ]
    tim_cmd = [
        "python",
        "/workspace/tools/hf_jobs/entrypoint_tim_hf.py",
        "--config",
        tim_cfg,
    ]
    llm_cmd = [
        "python",
        "/workspace/tools/hf_jobs/entrypoint_hf_hydration.py",
        "llm-sidecars",
    ]

    if args.dry_run_submit:
        print("NU:TONIC: dry-run — printing Hugging Face Job specs only (nothing submitted).", flush=True)
    else:
        print(
            "NU:TONIC: submitting hydration to Hugging Face Jobs (sv-lfm → TiM → llm; no local weight load).",
            flush=True,
        )

    if args.dry_run_submit:
        apply_hf_tokens_for_hub(write=True)
        submit_hydration_job(
            docker_image=args.sv_image,
            command=sv_cmd,
            flavor_name=args.sv_flavor,
            timeout=args.timeout,
            dataset_volume="NuTonic/poidata",
            dataset_mount_path="/mnt/poidata",
            dataset_revision=None,
            env={**env_sv_lfm},
            secrets=_collect_secrets_for_sv(),
            labels=None,
            dry_run=True,
        )
        if not args.skip_tim:
            assert args.tim_image
            submit_hydration_job(
                docker_image=args.tim_image,
                command=tim_cmd,
                flavor_name=args.tim_flavor,
                timeout=args.timeout,
                dataset_volume="NuTonic/poidata",
                dataset_mount_path="/mnt/poidata",
                dataset_revision=None,
                env={**env_common},
                secrets=_collect_secrets_for_tim_llm(),
                labels=None,
                dry_run=True,
            )
        submit_hydration_job(
            docker_image=llm_image,
            command=llm_cmd,
            flavor_name=args.llm_flavor,
            timeout=args.timeout,
            dataset_volume="NuTonic/poidata",
            dataset_mount_path="/mnt/poidata",
            dataset_revision=None,
            env={**env_llm},
            secrets=_collect_secrets_for_tim_llm(),
            labels=None,
            dry_run=True,
        )
        return 0

    apply_hf_tokens_for_hub(write=True)
    if not (os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")):
        print("Need HF_API_WRITE or HF_TOKEN to submit Jobs.", file=sys.stderr)
        return 3

    sv_secrets = _collect_secrets_for_sv()
    if "HF_TOKEN" not in sv_secrets:
        print("Need HF_API_WRITE or HF_TOKEN for container uploads.", file=sys.stderr)
        return 3
    if "GOOGLE_MAPS_API_KEY" not in sv_secrets and "GOOGLE_STREETVIEW_API_KEY" not in sv_secrets:
        print("Need GOOGLE_MAPS_API_KEY or GOOGLE_STREETVIEW_API_KEY in env for sv-lfm Job.", file=sys.stderr)
        return 3
    if "MAPBOX_ACCESS_TOKEN" not in sv_secrets and "MAPBOX_TOKEN" not in sv_secrets:
        print("Need MAPBOX_ACCESS_TOKEN (or MAPBOX_TOKEN) in env for sv-lfm Job.", file=sys.stderr)
        return 3

    tim_llm_secrets = _collect_secrets_for_tim_llm()
    if "HF_TOKEN" not in tim_llm_secrets:
        print("Need HF_API_WRITE or HF_TOKEN for TiM / LLM job uploads.", file=sys.stderr)
        return 3

    max_wait = args.max_wait_minutes * 60.0

    job_sv = submit_hydration_job(
        docker_image=args.sv_image,
        command=sv_cmd,
        flavor_name=args.sv_flavor,
        timeout=args.timeout,
        dataset_volume="NuTonic/poidata",
        dataset_mount_path="/mnt/poidata",
        dataset_revision=None,
        env={**env_sv_lfm},
        secrets=sv_secrets,
        labels=None,
        dry_run=False,
    )
    assert job_sv is not None
    print(job_sv.url, flush=True)
    try:
        _wait_job(job_sv.id, poll_sec=args.poll_seconds, max_wait_sec=max_wait)
    except (RuntimeError, TimeoutError) as e:
        print(str(e), file=sys.stderr)
        return 4

    job_tim = None
    if not args.skip_tim:
        assert args.tim_image
        job_tim = submit_hydration_job(
            docker_image=args.tim_image,
            command=tim_cmd,
            flavor_name=args.tim_flavor,
            timeout=args.timeout,
            dataset_volume="NuTonic/poidata",
            dataset_mount_path="/mnt/poidata",
            dataset_revision=None,
            env={**env_common},
            secrets=tim_llm_secrets,
            labels=None,
            dry_run=False,
        )
        assert job_tim is not None
        print(job_tim.url, flush=True)
        try:
            _wait_job(job_tim.id, poll_sec=args.poll_seconds, max_wait_sec=max_wait)
        except (RuntimeError, TimeoutError) as e:
            print(str(e), file=sys.stderr)
            return 5

    job_llm = submit_hydration_job(
        docker_image=llm_image,
        command=llm_cmd,
        flavor_name=args.llm_flavor,
        timeout=args.timeout,
        dataset_volume="NuTonic/poidata",
        dataset_mount_path="/mnt/poidata",
        dataset_revision=None,
        env={**env_llm},
        secrets=tim_llm_secrets,
        labels=None,
        dry_run=False,
    )
    assert job_llm is not None
    print(job_llm.url, flush=True)
    try:
        _wait_job(job_llm.id, poll_sec=args.poll_seconds, max_wait_sec=max_wait)
    except (RuntimeError, TimeoutError) as e:
        print(str(e), file=sys.stderr)
        return 6

    if args.skip_download:
        out: dict[str, object] = {
            "sv_job_id": job_sv.id,
            "llm_job_id": job_llm.id,
            "content_version": args.content_version,
            "output_dataset": args.output_dataset,
        }
        if job_tim is not None:
            out["tim_job_id"] = job_tim.id
        print(json.dumps(out), flush=True)
        return 0

    apply_hf_read_token()
    if not (os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")):
        apply_hf_tokens_for_hub(write=True)

    allow = f"runs/{args.content_version}/**"
    dl = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "download_hydration_outputs.py"),
            "--repo-id",
            args.output_dataset,
            "--allow-patterns",
            allow,
        ],
        cwd=str(REPO_ROOT),
    )
    return int(dl.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
