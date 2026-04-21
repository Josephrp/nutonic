"""Upload built dataset folder to Hugging Face Hub (dataset repo)."""

from __future__ import annotations

import os
import time
from pathlib import Path


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

    api = HfApi(token=token)

    def _create() -> None:
        api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)

    def _upload() -> None:
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
