"""Upload built dataset folder to Hugging Face Hub (dataset repo)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


def _resolve_hf_token(explicit: str | None) -> str:
    raw = (explicit or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if not raw:
        raise RuntimeError(
            "HF_TOKEN or HUGGING_FACE_HUB_TOKEN must be set (non-empty) to upload. "
            "Create a fine-grained or classic token with write access to the target dataset repo."
        )
    # Strip common mistake: quoted token in .env
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()
    return raw


def _validate_repo_id(repo_id: str) -> None:
    rid = repo_id.strip()
    if "/" not in rid or rid.count("/") != 1 or rid.startswith("/") or rid.endswith("/"):
        raise ValueError(
            f"Invalid Hugging Face repo id {repo_id!r}; expected ``org_or_user/repo_name`` (exactly one slash)."
        )


_HUB_DIR_HARD_LIMIT = 10_000
_DEFAULT_SHARD_MAX_FILES_PER_DIR = 8_000


def _count_flat_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for p in path.iterdir() if p.is_file())


def _iter_offending_dirs(root: Path, *, limit: int) -> list[tuple[str, int]]:
    """
    Return (relative_posix_dir, direct_file_count) for directories that exceed Hub limits.

    The Hub limit that bites SFT builds is **direct children** in folders like ``images/``.
    """
    candidates = [root / "images", root / "metadata", root / "mapbox_stills", root / "overlays"]
    bad: list[tuple[str, int]] = []
    for d in candidates:
        n = _count_flat_files(d)
        if n > limit:
            bad.append((d.relative_to(root).as_posix(), n))
    return sorted(bad, key=lambda x: -x[1])


def _maybe_shard_for_hub(root: Path) -> Path:
    """
    If the dataset contains >10k files in a single directory (Hub hard limit),
    create a sharded copy next to it (using hardlinks when possible) and return that path.
    """
    bad = _iter_offending_dirs(root, limit=_HUB_DIR_HARD_LIMIT)
    if not bad:
        return root

    # Create a deterministic sibling so retries are resumable.
    dst = root.with_name(root.name + "_hub")
    if dst.exists():
        # If user reruns after a failed upload, reuse the already-sharded copy.
        # We still trust the shard script to be deterministic.
        return dst

    repo_root = Path(__file__).resolve().parents[2]
    shard_script = repo_root / "data" / "scripts" / "shard_lfm_vl_dataset_for_hub.py"
    if not shard_script.is_file():
        raise FileNotFoundError(f"Missing sharding utility: {shard_script}")

    # Prefer hardlinks to avoid duplicating PNG bytes (works only on same filesystem).
    cmd = [
        sys.executable,
        str(shard_script),
        "--src",
        str(root),
        "--dst",
        str(dst),
        "--max-files-per-dir",
        str(_DEFAULT_SHARD_MAX_FILES_PER_DIR),
        "--link",
        "hard",
    ]
    print(
        f"Hub sharding required (>{_HUB_DIR_HARD_LIMIT} files in a directory). "
        f"Creating sharded copy at {dst} (hardlinks). Offenders={bad}",
        flush=True,
    )
    subprocess.run(cmd, check=True)
    return dst


def upload_dataset_folder(
    local_dir: Path,
    repo_id: str,
    *,
    private: bool = False,
    token: str | None = None,
) -> None:
    """
    Upload ``local_dir`` tree to ``repo_id`` (``org/name``), ``repo_type=dataset``.

    Retries transient Hub / CDN errors (429, 5xx). Ensures repo exists before upload.
    """
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.errors import HfHubHTTPError
    except ImportError as e:  # pragma: no cover
        raise ImportError("huggingface_hub is required for upload. pip install huggingface_hub") from e

    _validate_repo_id(repo_id)
    token = _resolve_hf_token(token)
    root = local_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Upload root is not a directory: {root}")

    # If we exceed Hub per-directory hard limits, shard first (rewrites JSONL + metadata refs).
    root = _maybe_shard_for_hub(root)

    api = HfApi(token=token)

    def _create() -> None:
        api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)

    def _upload() -> None:
        # Prefer upload_large_folder when available: it chunks commits and avoids 413/commit-size issues.
        upload_large = getattr(api, "upload_large_folder", None)
        if callable(upload_large):
            # huggingface_hub has had API signature changes across versions.
            # We call it with only the kwargs it actually supports.
            import inspect

            sig = inspect.signature(upload_large)
            supported = set(sig.parameters.keys())
            kwargs = {
                "folder_path": str(root),
                "repo_id": repo_id,
                "repo_type": "dataset",
                "token": token,
                "commit_message": "Dataset sync from nutonic build",
            }
            kwargs = {k: v for k, v in kwargs.items() if k in supported}
            upload_large(**kwargs)
            return
        api.upload_folder(
            folder_path=str(root),
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            commit_message="Dataset sync from nutonic build",
        )

    for attempt in range(6):
        try:
            _create()
            _upload()
            return
        except HfHubHTTPError as e:
            code = e.response.status_code if e.response is not None else None
            retryable = code in (408, 409, 425, 429, 500, 502, 503, 504)
            if not retryable or attempt >= 5:
                raise RuntimeError(
                    f"Hugging Face Hub upload failed for dataset {repo_id!r} (HTTP {code}): {e}\n"
                    "Check: token has ``write`` on this repo, repo id is correct, and "
                    "``pip install -U huggingface_hub`` is recent enough."
                ) from e
            delay = min(60.0, 2.0**attempt)
            time.sleep(delay)
        except Exception as e:
            raise RuntimeError(
                f"Hugging Face Hub upload failed for dataset {repo_id!r}: {e}\n"
                "Check HF_TOKEN / HUGGING_FACE_HUB_TOKEN, network, and that ``huggingface_hub`` is installed."
            ) from e
