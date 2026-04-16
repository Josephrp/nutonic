"""Ensure Hugging Face Hub dataset repos exist before ``upload_folder``."""

from __future__ import annotations

import os

from huggingface_hub import HfApi


def ensure_output_dataset_repo(api: HfApi, repo_id: str) -> None:
    """
    Create ``repo_id`` as a dataset if it does not exist yet (``exist_ok=True``).

    Env:
      ``NUTONIC_SKIP_CREATE_OUTPUT_DATASET`` — if ``1``, skip (fail on missing repo at upload).
      ``NUTONIC_HYDRATION_OUTPUT_PUBLIC`` — if ``1``, create as public; default private.
    """
    if os.environ.get("NUTONIC_SKIP_CREATE_OUTPUT_DATASET", "").strip() == "1":
        return
    private = os.environ.get("NUTONIC_HYDRATION_OUTPUT_PUBLIC", "").strip() != "1"
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
