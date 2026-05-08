"""Domain errors for Street View sampling (HTTP mapping in ``main``)."""

from __future__ import annotations

from typing import Any


class StreetViewInsufficientCoverageError(Exception):
    """Raised when stochastic/omni sampling cannot collect ``count`` frames within attempt caps."""

    def __init__(self, message: str, *, debug: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.debug = debug


class StreetViewMetadataError(Exception):
    """Raised when metadata indicates a hard failure (not simple ZERO_RESULTS at an anchor)."""

    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status
