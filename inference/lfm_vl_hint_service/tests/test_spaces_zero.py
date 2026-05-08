from __future__ import annotations

from lfm_vl_hint_service.spaces_zero import apply_zero_gpu


def test_apply_zero_gpu_noop_without_spaces() -> None:
    def inc(x: int) -> int:
        return x + 1

    wrapped = apply_zero_gpu(inc)
    assert wrapped(2) == 3
