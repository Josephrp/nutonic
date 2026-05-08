"""Capture TiM ``GenerationSampler.generate`` outputs without forking TerraTorch."""

from __future__ import annotations

import functools
from typing import Any, Callable


def attach_tim_sampler_capture(sampler: Any, storage: dict[str, Any]) -> Callable[..., Any]:
    """
    Wrap ``sampler.generate`` so the returned dict is shallow-stored in ``storage['tim']``.

    TerraMindTiM.forward calls ``self.sampler.generate`` internally; this wrapper
    preserves the original callable while retaining the last TiM modality tensors.
    """
    orig = sampler.generate

    @functools.wraps(orig)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        out = orig(*args, **kwargs)
        storage["tim"] = out
        return out

    sampler.generate = _wrapped  # type: ignore[method-assign]
    return orig
