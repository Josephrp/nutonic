#!/usr/bin/env python3
"""
Container entrypoint for Hugging Face Jobs: hydrate from ``NuTonic/poidata`` mount and upload
artifacts to a Hub **dataset** (``NUTONIC_HYDRATION_OUTPUT_DATASET``).

Modes:
  ``sv-lfm`` — catalog import, geo + stills + useful_hints, pano + LFM-VL services, Street View batch, upload cache.
  ``llm-sidecars`` — import catalog from mount, run ``narrative_llm_batch`` (stub or live), upload ``narrative/`` only.

Environment (typical):
  ``CONTENT_VERSION`` — cache segment / run id (required).
  ``POIDATA_MOUNT`` — dataset mount path (default ``/mnt/poidata``).
  ``NUTONIC_HYDRATION_OUTPUT_DATASET`` — target dataset repo id for ``upload_folder``.
  ``GOOGLE_MAPS_API_KEY`` or ``GOOGLE_STREETVIEW_API_KEY``, ``MAPBOX_ACCESS_TOKEN`` (sv-lfm).
  ``HF_TOKEN`` — Hub token (injected via Job secret) for uploads.
  ``NUTONIC_POI_LIMIT`` — if set (positive int), import **only** ``geoguessr_poi_12`` (first N by sorted
  ``poi_*`` order) and pass the same limit to the Street View batch (skips the dual 120+12 merge).
  ``NUTONIC_SKIP_GEO_HINTS`` — if ``1``, skip ``build_poi_geo_context`` / ``compile_useful_hint_tiers``
  (still runs Mapbox stills + batch without useful-hints injection).
  ``NUTONIC_POIDATA_REPO`` — dataset id for fallback ``snapshot_download`` (default ``NuTonic/poidata``).
  ``NUTONIC_NO_POIDATA_SNAPSHOT`` — if ``1``, do not pull missing trees from Hub (fail fast instead).
  ``NUTONIC_SKIP_CREATE_OUTPUT_DATASET`` — if ``1``, do not ``create_repo`` before upload (Hub 404 if missing).
  ``NUTONIC_HYDRATION_OUTPUT_PUBLIC`` — if ``1``, create output dataset as public when auto-creating; default private.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

_HF_JOBS_DIR = Path(__file__).resolve().parent
if str(_HF_JOBS_DIR) not in sys.path:
    sys.path.insert(0, str(_HF_JOBS_DIR))
import hf_output_dataset  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _poi_limit_argv() -> list[str]:
    raw = os.environ.get("NUTONIC_POI_LIMIT", "").strip()
    if not raw:
        return []
    try:
        n = int(raw)
    except ValueError:
        return []
    if n < 1:
        return []
    return ["--poi-limit", str(n)]


def _skip_geo_hints() -> bool:
    return os.environ.get("NUTONIC_SKIP_GEO_HINTS", "").strip() == "1"


def _load_hub_token_into_env() -> None:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if tok and not os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        os.environ["HUGGING_FACE_HUB_TOKEN"] = tok


def _tree_has_layout_b(root: Path) -> bool:
    return root.is_dir() and any(root.glob("poi_*/poi.json"))


def _find_tree_src(mount: Path, tree_name: str) -> Path | None:
    """Locate a Layout-B POI root (``poi_*/poi.json``) under the dataset mount."""
    candidates: list[Path] = [mount / tree_name]
    try:
        for child in sorted(mount.iterdir()):
            if child.is_dir():
                candidates.append(child / tree_name)
    except OSError:
        pass
    for c in candidates:
        if _tree_has_layout_b(c):
            return c
    for pat in (f"*/{tree_name}", f"*/*/{tree_name}", f"*/*/*/{tree_name}"):
        try:
            for p in mount.glob(pat):
                if p.is_dir() and _tree_has_layout_b(p):
                    return p
        except OSError:
            continue
    return None


def _list_mount_top(mount: Path) -> None:
    try:
        names = sorted(p.name for p in mount.iterdir())
        print(f"entrypoint: {mount} top-level ({len(names)}): {names[:60]}", file=sys.stderr)
    except OSError as e:
        print(f"entrypoint: cannot list {mount}: {e}", file=sys.stderr)


def _snapshot_pull_trees(trees: list[str]) -> None:
    if os.environ.get("NUTONIC_NO_POIDATA_SNAPSHOT", "").strip() == "1":
        raise RuntimeError(
            "POI trees missing under data/downloads and NUTONIC_NO_POIDATA_SNAPSHOT=1; refusing Hub snapshot."
        )
    from huggingface_hub import snapshot_download

    _load_hub_token_into_env()
    repo = os.environ.get("NUTONIC_POIDATA_REPO", "NuTonic/poidata").strip()
    dest = REPO_ROOT / "data" / "downloads"
    dest.mkdir(parents=True, exist_ok=True)
    patterns = [f"{t}/**" for t in trees]
    print(f"entrypoint: snapshot_download repo={repo!r} patterns={patterns} -> {dest}", file=sys.stderr)
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        local_dir=str(dest),
        allow_patterns=patterns,
    )


def _ensure_poi_trees(mount: Path, *, required: tuple[str, ...]) -> None:
    """
    Symlink ``geoguessr_poi_*`` from the HF dataset volume into ``data/downloads/``; if still
    missing Layout-B files, pull those subtrees from the Hub (needs ``HF_TOKEN``).
    """
    dd = REPO_ROOT / "data" / "downloads"
    dd.mkdir(parents=True, exist_ok=True)
    for name in ("geoguessr_poi_12", "geoguessr_poi_120"):
        if name not in required:
            continue
        dst = dd / name
        if dst.exists() or dst.is_symlink():
            if _tree_has_layout_b(dst):
                continue
            if dst.is_symlink():
                dst.unlink(missing_ok=True)
            elif dst.is_dir():
                try:
                    kids = list(dst.iterdir())
                except OSError:
                    kids = [True]
                if not kids:
                    dst.rmdir()
        if dst.exists() or dst.is_symlink():
            continue
        src = _find_tree_src(mount, name)
        if src is None:
            print(f"entrypoint: no Layout-B tree {name!r} under {mount}", file=sys.stderr)
            continue
        dst.symlink_to(src, target_is_directory=True)
        print(f"entrypoint: linked {dst} -> {src}", file=sys.stderr)

    missing = [t for t in required if not _tree_has_layout_b(dd / t)]
    if missing:
        _list_mount_top(mount)
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if missing and tok:
        print(f"entrypoint: pulling missing POI trees from Hub: {missing}", file=sys.stderr)
        _snapshot_pull_trees(missing)
        missing = [t for t in required if not _tree_has_layout_b(dd / t)]
    if missing:
        raise RuntimeError(
            f"Missing POI trees {missing!r} under {dd}. "
            f"Dataset volume {mount} did not contain usable geoguessr_poi_* Layout-B paths, "
            "and Hub snapshot did not populate them (check HF_TOKEN, repo id NUTONIC_POIDATA_REPO, "
            "and that the dataset has file-tree snapshots under geoguessr_poi_12/ / geoguessr_poi_120/)."
        )


def _required_poi_trees() -> tuple[str, ...]:
    return ("geoguessr_poi_12",) if _poi_limit_argv() else ("geoguessr_poi_12", "geoguessr_poi_120")


def _run_script(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(argv), file=sys.stderr)
    merged = {**os.environ, **(env or {})}
    rc = subprocess.run(argv, cwd=str(REPO_ROOT), env=merged, check=False).returncode
    if rc != 0:
        raise RuntimeError(f"command failed rc={rc}: {' '.join(argv)}")


def _wait_health(url: str, *, label: str, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err: str | None = None
    base = url.rstrip("/") + "/health"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(base)
            if r.status_code == 200:
                return
            last_err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(2.0)
    raise RuntimeError(f"{label} health failed: {base} (last: {last_err})")


def _upload_folder(local_dir: Path, *, path_in_repo: str) -> None:
    from huggingface_hub import HfApi

    repo_id = os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "").strip()
    if not repo_id:
        raise RuntimeError("NUTONIC_HYDRATION_OUTPUT_DATASET is not set")
    if not local_dir.is_dir():
        raise RuntimeError(f"upload source missing: {local_dir}")
    _load_hub_token_into_env()
    api = HfApi()
    hf_output_dataset.ensure_output_dataset_repo(api, repo_id)
    api.upload_folder(
        folder_path=str(local_dir),
        repo_id=repo_id,
        repo_type="dataset",
        path_in_repo=path_in_repo,
    )
    print(f"entrypoint: uploaded {local_dir} -> dataset:{repo_id}/{path_in_repo}", file=sys.stderr)


def mode_llm_sidecars(cv: str) -> int:
    mount = Path(os.environ.get("POIDATA_MOUNT", "/mnt/poidata"))
    _ensure_poi_trees(mount, required=_required_poi_trees())
    py = sys.executable
    lim = _poi_limit_argv()
    if lim:
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--content-version",
                cv,
                "--ranked-split",
                "half",
                *lim,
            ]
        )
    else:
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_120"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--content-version",
                cv,
                "--ranked-split",
                "half",
            ]
        )
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--force",
                "--content-version",
                cv,
                "--ranked-split",
                "half",
            ]
        )
    out_narr = REPO_ROOT / "data" / "cache" / cv / "narrative"
    _run_script(
        [
            py,
            str(REPO_ROOT / "data" / "scripts" / "narrative_llm_batch.py"),
            "--content-version",
            cv,
            "--catalog-root",
            str(REPO_ROOT / "data" / "catalog"),
            "--output-dir",
            str(out_narr),
        ]
    )
    _upload_folder(out_narr, path_in_repo=f"runs/{cv}/narrative")
    return 0


def mode_sv_lfm(cv: str, *, pano_port: int, lfm_port: int) -> int:
    if not (os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_STREETVIEW_API_KEY")):
        print("entrypoint sv-lfm: missing GOOGLE_MAPS_API_KEY / GOOGLE_STREETVIEW_API_KEY", file=sys.stderr)
        return 2
    if not (os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_TOKEN")):
        print("entrypoint sv-lfm: missing MAPBOX_ACCESS_TOKEN (or MAPBOX_TOKEN)", file=sys.stderr)
        return 2

    mount = Path(os.environ.get("POIDATA_MOUNT", "/mnt/poidata"))
    _ensure_poi_trees(mount, required=_required_poi_trees())
    py = sys.executable
    os.environ["NUTONIC_CONTENT_VERSION"] = cv
    lim = _poi_limit_argv()

    if lim:
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--content-version",
                cv,
                "--ranked-split",
                "half",
                *lim,
            ]
        )
    else:
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_120"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--content-version",
                cv,
                "--ranked-split",
                "half",
            ]
        )
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(REPO_ROOT / "data" / "downloads" / "geoguessr_poi_12"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--force",
                "--content-version",
                cv,
                "--ranked-split",
                "half",
            ]
        )
    _run_script([py, str(REPO_ROOT / "data" / "scripts" / "catalog_lint.py")])
    _run_script([py, str(REPO_ROOT / "data" / "scripts" / "fetch_geo_baselines.py")])
    hints_dir = REPO_ROOT / "data" / "cache" / cv / "useful_hints"
    if not _skip_geo_hints():
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "build_poi_geo_context.py"),
                "--catalog-root",
                str(REPO_ROOT / "data" / "catalog"),
                "--content-version",
                cv,
            ]
        )
        geo_dir = REPO_ROOT / "data" / "cache" / cv / "geo_context"
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "compile_useful_hint_tiers.py"),
                "--content-version",
                cv,
                "--geo-context-dir",
                str(geo_dir),
                "--output-dir",
                str(hints_dir),
            ]
        )
    else:
        hints_dir.mkdir(parents=True, exist_ok=True)
    still_meta = REPO_ROOT / "data" / "cache" / cv / "build_stills"
    _run_script(
        [
            py,
            str(REPO_ROOT / "data" / "scripts" / "render_mapbox_still.py"),
            "--catalog-root",
            str(REPO_ROOT / "data" / "catalog"),
            "--meta-dir",
            str(still_meta),
            "--allow-network",
        ]
    )

    pano_url = f"http://127.0.0.1:{pano_port}"
    lfm_url = f"http://127.0.0.1:{lfm_port}"
    pano_cwd = REPO_ROOT / "inference" / "streetview_pano_service"
    lfm_cwd = REPO_ROOT / "inference" / "lfm_vl_hint_service"
    pano_src = pano_cwd / "src"
    lfm_src = lfm_cwd / "src"
    pano_env = {
        **os.environ,
        "STREETVIEW_PROVIDER": "google",
        "PYTHONPATH": str(pano_src)
        + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
    }
    lfm_env = {
        **os.environ,
        "LFM_VL_BACKEND": "transformers",
        "PYTHONPATH": str(lfm_src)
        + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
    }
    pano_proc = subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "streetview_pano_service.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(pano_port),
        ],
        cwd=str(pano_cwd),
        env=pano_env,
    )
    lfm_proc = subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "lfm_vl_hint_service.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(lfm_port),
        ],
        cwd=str(lfm_cwd),
        env=lfm_env,
    )
    try:
        _wait_health(pano_url, label="pano", timeout_sec=float(os.environ.get("NUTONIC_PANO_READY_SEC", "600")))
        _wait_health(lfm_url, label="lfm", timeout_sec=float(os.environ.get("NUTONIC_LFM_READY_SEC", "900")))
        still_index = still_meta / "still_index.json"
        batch = [
            py,
            str(REPO_ROOT / "tools" / "batch_streetview_hints.py"),
            "--catalog-root",
            str(REPO_ROOT / "data" / "catalog"),
            "--pano-service-url",
            pano_url,
            "--lfm-vl-url",
            lfm_url,
            "--content-version",
            cv,
            "--still-index",
            str(still_index),
            "--prompt-template-version",
            "transformers-v1",
            "--timeout-sec",
            os.environ.get("NUTONIC_BATCH_TIMEOUT_SEC", "600"),
            "--allow-partial",
            *lim,
        ]
        if not _skip_geo_hints():
            idx = batch.index("--still-index") + 2
            batch.insert(idx, "--useful-hints-dir")
            batch.insert(idx + 1, str(hints_dir))
        _run_script(batch)
    finally:
        for proc in (lfm_proc, pano_proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()

    cache_cv = REPO_ROOT / "data" / "cache" / cv
    _upload_folder(cache_cv, path_in_repo=f"runs/{cv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="NU:TONIC HF Job hydration entrypoint")
    p.add_argument("mode", choices=("sv-lfm", "llm-sidecars"))
    p.add_argument("--pano-port", type=int, default=7861)
    p.add_argument("--lfm-port", type=int, default=7862)
    args = p.parse_args(argv)

    cv = os.environ.get("CONTENT_VERSION", "").strip()
    if not cv:
        print("CONTENT_VERSION must be set", file=sys.stderr)
        return 2

    try:
        if args.mode == "sv-lfm":
            return mode_sv_lfm(cv, pano_port=args.pano_port, lfm_port=args.lfm_port)
        return mode_llm_sidecars(cv)
    except Exception as e:  # noqa: BLE001
        print(f"entrypoint: {e}", file=sys.stderr)
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
