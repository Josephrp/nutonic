"""
Map NU:TONIC env vars to Hugging Face Hub client expectations.

The Hub SDK reads ``HUGGING_FACE_HUB_TOKEN`` and ``HF_TOKEN`` (see ``huggingface_hub`` docs).
This repo also supports::

    HF_API_READ   — preferred for snapshot_download / read-only Hub access
    HF_API_WRITE  — preferred for uploads, Job secrets, and write-capable Hub calls

Call :func:`apply_hf_read_token` before read operations and :func:`apply_hf_write_token`
before uploads. :func:`apply_hf_tokens_for_hub` sets read first, then upgrades to write when
only a write token is available for both.
"""

from __future__ import annotations

import os


def apply_hf_read_token() -> None:
    """Ensure read-capable Hub auth (does not downgrade an existing write token)."""
    if os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN"):
        return
    read_tok = os.environ.get("HF_API_READ")
    if read_tok:
        os.environ["HUGGING_FACE_HUB_TOKEN"] = read_tok


def apply_hf_write_token() -> None:
    """Prefer a dedicated write token for mutating Hub APIs."""
    write_tok = os.environ.get("HF_API_WRITE")
    if write_tok:
        os.environ["HUGGING_FACE_HUB_TOKEN"] = write_tok
        os.environ["HF_TOKEN"] = write_tok
        return
    apply_hf_read_token()


def apply_hf_tokens_for_hub(*, write: bool) -> None:
    """``write=False``: read token only. ``write=True``: HF_API_WRITE or read fallback."""
    if write:
        apply_hf_write_token()
        if not (os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")):
            apply_hf_read_token()
    else:
        apply_hf_read_token()
