#!/usr/bin/env python3
"""
Hugging Face Job entrypoint: run TerraMind TiM batch from YAML, then upload ``/tmp/tim_hf_out``
to ``NUTONIC_HYDRATION_OUTPUT_DATASET`` at ``runs/<CONTENT_VERSION>/tim/``.

When ``runs/<CONTENT_VERSION>/reports/tim_batch_seed.json`` exists on the output dataset (written by
sv-lfm finalize) or under ``data/cache/<cv>/reports/`` locally, it replaces the static hf_job
``batch:`` list so TiM hydrates **every** POI in ``hydration_included_location_ids.json``, not only
the small template slice.

Secrets: ``HF_TOKEN`` (write-capable Hub token), same as other hydration jobs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

# TiM image only copies ``tools/hf_jobs/`` — import sibling module, not ``tools.hf_jobs.*``.
_HF_JOBS_DIR = Path(__file__).resolve().parent
if str(_HF_JOBS_DIR) not in sys.path:
    sys.path.insert(0, str(_HF_JOBS_DIR))
import hf_output_dataset  # noqa: E402
from tim_batch_seed import apply_tim_batch_seed_to_config, load_tim_batch_seed  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TIM_PKG_DIR = REPO_ROOT / "inference" / "terramind_tim_local"


def _hub_token() -> None:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if tok and not os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        os.environ["HUGGING_FACE_HUB_TOKEN"] = tok


def _resolve_tim_config_path(base_cfg: Path) -> Path:
    """
    When ``runs/<cv>/reports/tim_batch_seed.json`` exists (local cache or Hub), merge it into the
    YAML so TiM runs one STAC row per finalized POI (parity with ``hydration_included_location_ids.json``).
    """
    cv = os.environ.get("CONTENT_VERSION", "").strip()
    if not cv:
        return base_cfg

    local_seed = REPO_ROOT / "data" / "cache" / cv / "reports" / "tim_batch_seed.json"
    seed_path: Path | None = None
    if local_seed.is_file():
        seed_path = local_seed
    else:
        repo = os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "").strip()
        if repo:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError:
                hf_hub_download = None  # type: ignore[assignment]
            if hf_hub_download is not None:
                _hub_token()
                try:
                    p = hf_hub_download(
                        repo_id=repo,
                        repo_type="dataset",
                        filename=f"runs/{cv}/reports/tim_batch_seed.json",
                    )
                    seed_path = Path(p)
                except Exception as e:  # noqa: BLE001 — optional artifact for legacy sv-lfm
                    print(
                        f"entrypoint_tim_hf: tim_batch_seed.json not available ({e}); "
                        "using static YAML batch (may not cover all included POIs).",
                        file=sys.stderr,
                    )

    if seed_path is None:
        return base_cfg

    cfg = yaml.safe_load(base_cfg.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise RuntimeError(f"{base_cfg}: expected YAML mapping at root")
    seed = load_tim_batch_seed(seed_path)
    merged = apply_tim_batch_seed_to_config(cfg, seed)
    out = Path("/tmp/tim_cfg_merged.yaml")
    out.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8")
    n_batch = len(merged.get("batch") or [])
    print(f"entrypoint_tim_hf: merged tim_batch_seed ({seed_path}) -> {out} ({n_batch} batch row(s))", file=sys.stderr)
    return out


def _upload(out_dir: Path, *, cv: str) -> None:
    from huggingface_hub import HfApi

    repo_id = os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "").strip()
    if not repo_id:
        raise RuntimeError("NUTONIC_HYDRATION_OUTPUT_DATASET is not set")
    _hub_token()
    api = HfApi()
    hf_output_dataset.ensure_output_dataset_repo(api, repo_id)
    api.upload_folder(
        folder_path=str(out_dir),
        repo_id=repo_id,
        repo_type="dataset",
        path_in_repo=f"runs/{cv}/tim",
    )
    print(f"entrypoint_tim_hf: uploaded {out_dir} -> {repo_id}/runs/{cv}/tim", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TiM batch + Hub upload for HF Jobs.")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="TiM run YAML (default: env TIM_HF_CONFIG or packaged hf_job config).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/tim_hf_out"),
        help="Directory for tim_run.json + tim_export.jsonl before upload.",
    )
    args = p.parse_args(argv)

    cv = os.environ.get("CONTENT_VERSION", "").strip()
    if not cv:
        print("CONTENT_VERSION must be set", file=sys.stderr)
        return 2

    cfg = args.config
    if cfg is None:
        if os.environ.get("TIM_HF_CONFIG", "").strip():
            raw = os.environ["TIM_HF_CONFIG"].strip()
        elif os.environ.get("NUTONIC_POI_LIMIT", "").strip() == "5":
            raw = str(TIM_PKG_DIR / "config.hf_job_geoguessr_poi12_first5.yaml")
        else:
            raw = str(TIM_PKG_DIR / "config.hf_job_geoguessr_poi12_first3.yaml")
        cfg = Path(raw)
    cfg = _resolve_tim_config_path(cfg.resolve())

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    cmd = [
        py,
        "-m",
        "nutonic_terramind_tim_local",
        "run",
        "--config",
        str(cfg),
        "--output-dir",
        str(out_dir),
        "--device",
        os.environ.get("TIM_DEVICE_OVERRIDE", "cuda"),
    ]
    print("+", " ".join(cmd), file=sys.stderr)
    rc = subprocess.run(cmd, cwd=str(TIM_PKG_DIR), check=False).returncode
    if rc != 0:
        return int(rc)

    if os.environ.get("NUTONIC_TIM_SKIP_UPLOAD") == "1":
        print("entrypoint_tim_hf: NUTONIC_TIM_SKIP_UPLOAD=1 — skipping Hub upload", file=sys.stderr)
        return 0

    try:
        _upload(out_dir, cv=cv)
    except Exception as e:  # noqa: BLE001
        print(f"entrypoint_tim_hf: upload failed: {e}", file=sys.stderr)
        return 9
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
