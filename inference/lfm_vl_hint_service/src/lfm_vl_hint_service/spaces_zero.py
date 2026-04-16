"""
Hugging Face ZeroGPU (`@spaces.GPU`) compatibility.

`spaces` is optional: local / CI installs without it keep plain function calls.
On Hugging Face ZeroGPU Spaces, install the ``serve`` extra (``gradio`` + ``spaces``)
and run with Gradio mounted (see ``gradio_panel`` + ``main`` mount).
"""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def _zero_gpu_duration_seconds() -> int | None:
    raw = os.environ.get("LFM_VL_ZERO_GPU_DURATION")
    if raw is None or raw.strip() == "":
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def apply_zero_gpu(
    fn: F,
    *,
    duration: int | None = None,
    size: str | None = None,
) -> F:
    """
    Wrap *fn* with ``spaces.GPU`` when the ``spaces`` package is installed.

    ``duration`` / ``size`` match Hugging Face ZeroGPU docs; when *duration* is
    ``None``, ``LFM_VL_ZERO_GPU_DURATION`` may supply seconds (else HF default).
    """
    try:
        import spaces
    except ImportError:
        return fn

    eff_duration = duration if duration is not None else _zero_gpu_duration_seconds()
    kw: dict[str, Any] = {}
    if eff_duration is not None:
        kw["duration"] = eff_duration
    if size is not None:
        kw["size"] = size
    if kw:
        return spaces.GPU(fn, **kw)  # type: ignore[return-value]
    return spaces.GPU(fn)  # type: ignore[return-value]
