#!/usr/bin/env python3
"""
Container entrypoint for Hugging Face Jobs: hydrate from ``NuTonic/poidata`` mount and upload
artifacts to a Hub **dataset** (``NUTONIC_HYDRATION_OUTPUT_DATASET``).

Modes:
  ``sv-lfm`` — catalog import, geo + stills + useful_hints, pano + LFM-VL services, Street View batch,
  **finalize** (drop failed POIs, rewrite ``still_index.json``, emit ``reports/hydration_included_location_ids.json``),
  then emit ``reports/useful_hints_coverage.json`` (per-POI useful-hints file presence),
  ``reports/tim_batch_seed.json`` (coordinates for every finalized POI — consumed by the TiM Job),
  then upload cache.
  ``llm-sidecars`` — import catalog from mount, ``snapshot_download`` ``runs/<cv>/streetview/**`` from the output
  dataset (when configured) so narrative prompts see hydrated Street View + satellite text, then run
  ``narrative_llm_batch`` (dry-run or live via vLLM / OpenAI HTTP / in-process ``transformers`` / optional Ollama),
  upload ``narrative/`` only.

Environment (typical):
  ``CONTENT_VERSION`` — cache segment / run id (required).
  ``POIDATA_MOUNT`` — dataset mount path (default ``/mnt/poidata``).
  ``NUTONIC_HYDRATION_OUTPUT_DATASET`` — target dataset repo id for ``upload_folder``.
  ``GOOGLE_MAPS_API_KEY`` or ``GOOGLE_STREETVIEW_API_KEY`` (sv-lfm); ``MAPBOX_ACCESS_TOKEN`` unless
  ``NUTONIC_SKIP_MAPBOX_STILLS=1``.
  ``HF_TOKEN`` — Hub token (injected via Job secret) for uploads.
  ``NUTONIC_POI_LIMIT`` — if set (positive int), import the first N POIs by sorted ``poi_*`` order and pass
  the same limit to the Street View batch. Values **≤12** use ``downloads/geoguessr_poi_12`` only; values
  **>12** require ``geoguessr_poi_120`` on the mount (NuTonic/poidata ships 12 POIs under ``geoguessr_poi_12``
  and the larger tree under ``geoguessr_poi_120``). No dual 120+12 merge in limited mode.
  ``NUTONIC_SKIP_GEO_HINTS`` — if ``1``, skip ``build_poi_geo_context`` / ``compile_useful_hint_tiers``.
  ``NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL`` — if not ``0``/``false``/``no`` (default: allow), ``build_poi_geo_context`` is run with ``--allow-partial`` so one bad POI does not fail the Job.
  (still runs reference stills + batch without useful-hints injection).
  ``NUTONIC_SKIP_MAPBOX_STILLS`` — if ``1``, skip Mapbox Static API; reference stills come from
  ``render_mapbox_still.py --stac-reference-stills`` (Sentinel-2 Earth Search STAC) by default.
  Set ``NUTONIC_STAC_REFERENCE_STILLS=0`` for gray ``--placeholder-stills`` instead.
  ``MAPBOX_ACCESS_TOKEN`` not required when skipping Mapbox.
  ``NUTONIC_POIDATA_REPO`` — dataset id for fallback ``snapshot_download`` (default ``NuTonic/poidata``).
  ``NUTONIC_NO_POIDATA_SNAPSHOT`` — if ``1``, do not pull missing trees from Hub (fail fast instead).
  ``NUTONIC_SKIP_CREATE_OUTPUT_DATASET`` — if ``1``, do not ``create_repo`` before upload (Hub 404 if missing).
  ``NUTONIC_HYDRATION_OUTPUT_PUBLIC`` — if ``1``, create output dataset as public when auto-creating; default private.

  **LFM-VL (``sv-lfm`` only):** ``LFM_VL_BACKEND`` (default ``transformers`` if unset), ``LFM_VL_MODEL_ID``,
  ``LFM_OPENAI_BASE_URL`` / ``LFM_OPENAI_MODEL`` when using ``openai_compatible`` (vLLM sidecar), etc.

  **Narrative LLM (``llm-sidecars`` live):**   ``NUTONIC_NARRATIVE_LLM_LIVE=1``, ``NUTONIC_NARRATIVE_BACKEND`` one of
  ``transformers`` (default when unset), ``vllm``, ``openai``, ``ollama``; ``NUTONIC_VLLM_MODEL``, ``NUTONIC_VLLM_AUTOSTART``,
  ``NUTONIC_VLLM_PORT``, ``NUTONIC_NARRATIVE_OPENAI_*``, ``NUTONIC_NARRATIVE_TRANSFORMERS_MODEL``, ``OLLAMA_HOST``.

  **Street View sampling (optional, see ``tools/hf_jobs/pano_batch_env.py``):**
  ``NUTONIC_SHUFFLE_SEED``, ``NUTONIC_PANO_SAMPLING_MODE``, ``NUTONIC_PANO_JITTER_SEED``,
  ``NUTONIC_PANO_AREA_RADIUS_M``, ``NUTONIC_PANO_MIN_ANCHOR_SEPARATION_M``, ``NUTONIC_PANO_LEGACY_RADIUS_M``
  → forwarded as ``batch_streetview_hints.py`` CLI flags. Pano worker may read ``STREETVIEW_S2_*`` and
  ``STREETVIEW_EXPOSE_SAMPLING_DEBUG`` if set in the Job environment.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_HF_JOBS_DIR = Path(__file__).resolve().parent
if str(_HF_JOBS_DIR) not in sys.path:
    sys.path.insert(0, str(_HF_JOBS_DIR))
import hf_output_dataset  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

_DS = str(REPO_ROOT / "data" / "scripts")
if _DS not in sys.path:
    sys.path.insert(0, _DS)
try:
    from liquid_ai_defaults import DEFAULT_LFM_TEXT_HF_MODEL_ID, DEFAULT_LFM_VL_HF_MODEL_ID
except ImportError:
    DEFAULT_LFM_TEXT_HF_MODEL_ID = "LiquidAI/LFM2.5-1.2B-Instruct"
    DEFAULT_LFM_VL_HF_MODEL_ID = "LiquidAI/LFM2.5-VL-450M"


def _poi_limit_n() -> int | None:
    raw = os.environ.get("NUTONIC_POI_LIMIT", "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < 1:
        return None
    return n


def _poi_limit_argv() -> list[str]:
    n = _poi_limit_n()
    if n is None:
        return []
    return ["--poi-limit", str(n)]


def _limited_catalog_poi_root() -> Path:
    """
    When ``NUTONIC_POI_LIMIT`` requests more than the small Hub slice (12 under ``geoguessr_poi_12``),
    prefer ``geoguessr_poi_120`` so the catalog can actually contain N locations.
    """
    dd = REPO_ROOT / "data" / "downloads"
    small = dd / "geoguessr_poi_12"
    big = dd / "geoguessr_poi_120"
    n = _poi_limit_n()
    if n is not None and n > 12:
        if _tree_has_layout_b(big):
            print(
                f"entrypoint: NUTONIC_POI_LIMIT={n} > 12 — catalog import from geoguessr_poi_120 "
                "(geoguessr_poi_12 is a 12-POI slice on NuTonic/poidata).",
                file=sys.stderr,
            )
            return big
        print(
            "entrypoint: warning: NUTONIC_POI_LIMIT>12 but geoguessr_poi_120 missing or empty; "
            "falling back to geoguessr_poi_12 (catalog may cap at 12 locations).",
            file=sys.stderr,
        )
    return small


def _skip_geo_hints() -> bool:
    return os.environ.get("NUTONIC_SKIP_GEO_HINTS", "").strip() == "1"


def _skip_mapbox_stills() -> bool:
    return os.environ.get("NUTONIC_SKIP_MAPBOX_STILLS", "").strip() == "1"


def _use_stac_reference_stills() -> bool:
    """When skipping Mapbox, prefer Sentinel-2 STAC previews unless explicitly disabled."""
    v = os.environ.get("NUTONIC_STAC_REFERENCE_STILLS", "1").strip().lower()
    return v not in ("0", "false", "no")


def _geo_context_allow_partial_argv() -> list[str]:
    v = os.environ.get("NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL", "1").strip().lower()
    if v in ("0", "false", "no"):
        return []
    return ["--allow-partial"]


def _load_hub_token_into_env() -> None:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if tok and not os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        os.environ["HUGGING_FACE_HUB_TOKEN"] = tok


def _pull_output_dataset_streetview_for_narrative(cv: str) -> Path | None:
    """
    Materialize ``runs/<cv>/streetview/*.json`` from the output dataset under ``data/cache/runs/<cv>/``.

    ``narrative_llm_batch`` defaults to ``data/cache/<cv>/``, which only exists inside the sv-lfm Job;
    the llm-sidecars Job must re-fetch Street View JSON so ``prompts/llm/*.md`` clue placeholders resolve.
    """
    hub_aligned = REPO_ROOT / "data" / "cache" / "runs" / cv
    sv_dir = hub_aligned / "streetview"
    try:
        if sv_dir.is_dir() and any(sv_dir.glob("*.json")):
            print(f"entrypoint llm-sidecars: using existing streetview slice at {sv_dir}", file=sys.stderr)
            return hub_aligned
    except OSError:
        pass

    repo = os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "").strip()
    if not repo:
        print(
            "entrypoint llm-sidecars: NUTONIC_HYDRATION_OUTPUT_DATASET unset; "
            "narrative cannot load Street View JSON from Hub (clue placeholders only).",
            file=sys.stderr,
        )
        return None
    if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip():
        print(
            "entrypoint llm-sidecars: no HF_TOKEN for Hub read; narrative Street View clue pull skipped.",
            file=sys.stderr,
        )
        return None

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("entrypoint llm-sidecars: huggingface_hub missing; cannot pull streetview for narrative.", file=sys.stderr)
        return None

    _load_hub_token_into_env()
    cache_parent = REPO_ROOT / "data" / "cache"
    cache_parent.mkdir(parents=True, exist_ok=True)
    pat = f"runs/{cv}/streetview/**"
    try:
        snapshot_download(
            repo_id=repo,
            repo_type="dataset",
            local_dir=str(cache_parent),
            allow_patterns=[pat],
        )
    except Exception as e:  # noqa: BLE001
        print(f"entrypoint llm-sidecars: Hub snapshot for narrative streetview failed: {e}", file=sys.stderr)
        return None

    if not sv_dir.is_dir() or not any(sv_dir.glob("*.json")):
        print(f"entrypoint llm-sidecars: after snapshot, no JSON under {sv_dir}", file=sys.stderr)
        return None
    print(f"entrypoint llm-sidecars: pulled streetview for narrative -> {sv_dir}", file=sys.stderr)
    return hub_aligned


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
    n = _poi_limit_n()
    if n is None:
        return ("geoguessr_poi_12", "geoguessr_poi_120")
    if n > 12:
        return ("geoguessr_poi_12", "geoguessr_poi_120")
    return ("geoguessr_poi_12",)


def _run_script(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(argv), file=sys.stderr)
    merged = {**os.environ, **(env or {})}
    rc = subprocess.run(argv, cwd=str(REPO_ROOT), env=merged, check=False).returncode
    if rc != 0:
        raise RuntimeError(f"command failed rc={rc}: {' '.join(argv)}")


def _wait_openai_v1_models(v1_base: str, *, timeout_sec: float) -> None:
    """Poll OpenAI-compatible ``GET {v1_base}/models`` (vLLM / OpenAI)."""
    deadline = time.monotonic() + timeout_sec
    last_err: str | None = None
    root = v1_base.rstrip("/")
    if not root.endswith("/v1"):
        root = root + "/v1"
    url = f"{root}/models"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(url)
            if r.status_code == 200:
                return
            last_err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(2.0)
    raise RuntimeError(f"OpenAI-compatible /v1/models did not become ready at {url} (last: {last_err})")


def _wait_ollama_ready(*, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err: str | None = None
    base = (os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")) + "/api/tags"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(base)
            if r.status_code == 200:
                return
            last_err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(1.0)
    raise RuntimeError(f"ollama did not become ready at {base} (last: {last_err})")


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


USEFUL_HINTS_COVERAGE_SCHEMA = "nutonic.useful_hints_coverage.v1"


def _write_useful_hints_coverage_report(
    *,
    cache_cv: Path,
    location_ids: list[str],
    hints_dir: Path,
    content_version: str,
    skip_geo_hints: bool,
) -> None:
    """
    Per-location record of whether ``useful_hints/<location_id>.json`` exists after geo/hints pipeline.

    Written after Street View finalize so ``location_ids`` match the shipped cache segment.
    """
    rep = cache_cv / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for lid in location_ids:
        p = hints_dir / f"{lid}.json"
        if skip_geo_hints:
            rows.append(
                {
                    "location_id": lid,
                    "useful_hints_status": "skipped_geo_hints",
                    "path": None,
                }
            )
        elif p.is_file():
            rows.append(
                {
                    "location_id": lid,
                    "useful_hints_status": "present",
                    "path": f"runs/{content_version}/useful_hints/{lid}.json",
                }
            )
        else:
            rows.append(
                {
                    "location_id": lid,
                    "useful_hints_status": "absent",
                    "path": None,
                    "reason": "no useful_hints file after compile/geo pipeline",
                }
            )
    doc = {
        "content_version": content_version,
        "locations": rows,
        "schema_version": USEFUL_HINTS_COVERAGE_SCHEMA,
    }
    (rep / "useful_hints_coverage.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"entrypoint: wrote {rep / 'useful_hints_coverage.json'}", file=sys.stderr)


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


def _ensure_vllm_openai_server() -> tuple[subprocess.Popen[bytes] | None, str, str]:
    """
    For narrative ``openai`` backend: optionally start vLLM OpenAI server, then wait for ``/v1/models``.

    ``NUTONIC_VLLM_AUTOSTART=0`` — do not spawn; only wait on ``NUTONIC_VLLM_BASE`` /
    ``NUTONIC_NARRATIVE_OPENAI_BASE``. Chat ``model`` defaults to Liquid **LFM** text id when unset
    (see ``data/scripts/liquid_ai_defaults.py``).

    Returns ``(server_process_or_none, openai_v1_base, chat_model_id)``.
    """
    port = int(os.environ.get("NUTONIC_VLLM_PORT", "8000").strip() or "8000")
    autostart_raw = os.environ.get("NUTONIC_VLLM_AUTOSTART", "1").strip().lower()
    autostart = autostart_raw not in ("0", "false", "no", "")
    chat_model = (
        os.environ.get("NUTONIC_NARRATIVE_OPENAI_MODEL", "").strip()
        or os.environ.get("NUTONIC_VLLM_MODEL", "").strip()
        or DEFAULT_LFM_TEXT_HF_MODEL_ID
    )
    proc: subprocess.Popen[bytes] | None = None

    if not autostart:
        v1 = (
            os.environ.get("NUTONIC_VLLM_BASE", "").strip()
            or os.environ.get("NUTONIC_NARRATIVE_OPENAI_BASE", "").strip()
            or f"http://127.0.0.1:{port}/v1"
        ).rstrip("/")
        if not v1.endswith("/v1"):
            v1 = f"{v1}/v1"
        _wait_openai_v1_models(v1, timeout_sec=float(os.environ.get("NUTONIC_VLLM_READY_SEC", "900")))
        return None, v1, chat_model

    serve_model = os.environ.get("NUTONIC_VLLM_MODEL", "").strip() or chat_model
    chat_model = os.environ.get("NUTONIC_NARRATIVE_OPENAI_MODEL", "").strip() or serve_model
    custom = os.environ.get("NUTONIC_VLLM_SERVE_CMD", "").strip()
    if custom:
        proc = subprocess.Popen(
            shlex.split(custom),
            env={**os.environ},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    else:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "vllm.entrypoints.openai.api_server",
                "--model",
                serve_model,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env={**os.environ},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    v1 = f"http://127.0.0.1:{port}/v1"
    _wait_openai_v1_models(v1, timeout_sec=float(os.environ.get("NUTONIC_VLLM_READY_SEC", "900")))
    return proc, v1, chat_model


def mode_llm_sidecars(cv: str) -> int:
    mount = Path(os.environ.get("POIDATA_MOUNT", "/mnt/poidata"))
    _ensure_poi_trees(mount, required=_required_poi_trees())
    py = sys.executable
    lim = _poi_limit_argv()
    server_procs: list[subprocess.Popen[bytes]] = []
    if lim:
        _run_script(
            [
                py,
                str(REPO_ROOT / "data" / "scripts" / "catalog_import_poi.py"),
                "--poi-root",
                str(_limited_catalog_poi_root()),
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
    narr_hydration_root = _pull_output_dataset_streetview_for_narrative(cv)
    out_narr = REPO_ROOT / "data" / "cache" / cv / "narrative"
    try:
        want_live = os.environ.get("NUTONIC_NARRATIVE_LLM_LIVE", "").strip() == "1"
        narr_backend = os.environ.get("NUTONIC_NARRATIVE_BACKEND", "").strip().lower()
        if want_live and not narr_backend:
            # In-container Hugging Face causal LM (see data/scripts/liquid_ai_defaults.py). Avoids vLLM HTTP unless opted in.
            narr_backend = "transformers"
        narr = [
            py,
            str(REPO_ROOT / "data" / "scripts" / "narrative_llm_batch.py"),
            "--content-version",
            cv,
            "--catalog-root",
            str(REPO_ROOT / "data" / "catalog"),
            "--output-dir",
            str(out_narr),
        ]
        if narr_hydration_root is not None:
            narr += ["--hydration-cache-root", str(narr_hydration_root)]
        if want_live:
            if narr_backend == "ollama":
                if shutil.which("ollama"):
                    op = subprocess.Popen(
                        ["ollama", "serve"],
                        env={**os.environ},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    server_procs.append(op)
                    _wait_ollama_ready(timeout_sec=float(os.environ.get("NUTONIC_OLLAMA_READY_SEC", "180")))
                    if os.environ.get("NUTONIC_OLLAMA_PULL", "").strip() == "1":
                        model = os.environ.get("NUTONIC_OLLAMA_MODEL", "llama3.2").strip()
                        subprocess.run(["ollama", "pull", model], env={**os.environ}, check=False, timeout=3600)
                    narr += [
                        "--no-dry-run",
                        "--backend",
                        "ollama",
                        "--ollama-url",
                        (os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/") or "http://127.0.0.1:11434"),
                        "--ollama-model",
                        os.environ.get("NUTONIC_OLLAMA_MODEL", "llama3.2").strip(),
                    ]
                else:
                    print(
                        "entrypoint: NUTONIC_NARRATIVE_BACKEND=ollama but `ollama` not on PATH; "
                        "writing dry-run sidecar",
                        file=sys.stderr,
                    )
            elif narr_backend == "transformers":
                tm = (
                    os.environ.get("NUTONIC_NARRATIVE_TRANSFORMERS_MODEL", "").strip()
                    or DEFAULT_LFM_TEXT_HF_MODEL_ID
                )
                mtoks = os.environ.get("NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW", "512").strip()
                narr += [
                    "--no-dry-run",
                    "--backend",
                    "transformers",
                    "--transformers-model",
                    tm,
                    "--transformers-max-new-tokens",
                    mtoks,
                ]
            else:
                # Explicit ``vllm`` / ``openai``: OpenAI-compatible HTTP (vLLM or remote server).
                vproc, v1_base, chat_model = _ensure_vllm_openai_server()
                if vproc is not None:
                    server_procs.append(vproc)
                narr += [
                    "--no-dry-run",
                    "--backend",
                    "openai",
                    "--openai-base",
                    v1_base,
                    "--openai-model",
                    chat_model,
                ]
        _run_script(narr)
    finally:
        for sp in reversed(server_procs):
            if sp.poll() is None:
                sp.terminate()
                try:
                    sp.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    sp.kill()
    _upload_folder(out_narr, path_in_repo=f"runs/{cv}/narrative")
    return 0


def mode_sv_lfm(cv: str, *, pano_port: int, lfm_port: int) -> int:
    import pano_batch_env  # noqa: PLC0415 — only ``sv-lfm`` image ships ``pano_batch_env.py``; ``llm-sidecars`` omits it.

    if not (os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_STREETVIEW_API_KEY")):
        print("entrypoint sv-lfm: missing GOOGLE_MAPS_API_KEY / GOOGLE_STREETVIEW_API_KEY", file=sys.stderr)
        return 2
    if not _skip_mapbox_stills() and not (
        os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_TOKEN")
    ):
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
                str(_limited_catalog_poi_root()),
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
                *_geo_context_allow_partial_argv(),
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
    if _skip_mapbox_stills():
        still_extra = (
            ["--stac-reference-stills"]
            if _use_stac_reference_stills()
            else ["--placeholder-stills"]
        )
    else:
        still_extra = ["--allow-network"]
    _run_script(
        [
            py,
            str(REPO_ROOT / "data" / "scripts" / "render_mapbox_still.py"),
            "--catalog-root",
            str(REPO_ROOT / "data" / "catalog"),
            "--meta-dir",
            str(still_meta),
            *still_extra,
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
        **pano_batch_env.pano_service_env_pass_through(),
    }
    lfm_env = dict(os.environ)
    if not (lfm_env.get("LFM_VL_BACKEND") or "").strip():
        lfm_env["LFM_VL_BACKEND"] = "transformers"
    if not (lfm_env.get("LFM_VL_MODEL_ID") or "").strip():
        lfm_env["LFM_VL_MODEL_ID"] = DEFAULT_LFM_VL_HF_MODEL_ID
    lfm_pp = str(lfm_src)
    if lfm_env.get("PYTHONPATH"):
        lfm_env["PYTHONPATH"] = lfm_pp + os.pathsep + lfm_env["PYTHONPATH"]
    else:
        lfm_env["PYTHONPATH"] = lfm_pp
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
        # Street View + LFM pacing: reduce bursty load on Google (via pano) and GPU HTTP (LFM). Override via env.
        os.environ.setdefault("NUTONIC_BATCH_INTER_POI_SLEEP_SEC", "0.35")
        os.environ.setdefault("NUTONIC_BATCH_PANO_TO_LFM_SLEEP_SEC", "0.12")
        os.environ.setdefault("NUTONIC_BATCH_INTER_LFM_CHUNK_SLEEP_SEC", "0.06")
        os.environ.setdefault("NUTONIC_BATCH_HTTP_MAX_ATTEMPTS", "10")
        os.environ.setdefault("NUTONIC_BATCH_HTTP_BACKOFF_CAP_SEC", "48")
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
        batch.extend(pano_batch_env.pano_batch_cli_extras_from_environ())
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
    catalog_locs = REPO_ROOT / "data" / "catalog" / "locations"
    # Import only in sv-lfm: ``Dockerfile.hydration-llm`` copies a minimal ``tools/hf_jobs`` tree for llm-sidecars.
    from hydration_cache_finalize import finalize_hydration_cache_post_streetview  # noqa: PLC0415

    included = finalize_hydration_cache_post_streetview(
        cache_cv=cache_cv,
        catalog_locations_dir=catalog_locs,
        content_version=cv,
    )
    if not included:
        print(
            "entrypoint sv-lfm: no POIs remain after Street View finalize (all failed or missing outputs); "
            "refusing empty cache upload.",
            file=sys.stderr,
        )
        return 7

    _write_useful_hints_coverage_report(
        cache_cv=cache_cv,
        location_ids=included,
        hints_dir=hints_dir,
        content_version=cv,
        skip_geo_hints=_skip_geo_hints(),
    )

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
