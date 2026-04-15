"""Local TerraMind TiM (TerraTorch) batch export for NU:TONIC inference plane."""

from __future__ import annotations

from typing import Any

__all__ = ["run_tim_batch_export", "run_tim_forward_export"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from nutonic_terramind_tim_local import run as _run

        return getattr(_run, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
