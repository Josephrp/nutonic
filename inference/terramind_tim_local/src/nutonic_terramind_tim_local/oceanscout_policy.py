from __future__ import annotations

OCEANSCOUT_SHORELINE_POLICY: dict[str, float | str] = {
    "version": "1.0",
    "buffer_m": 500.0,
    "morphology_kernel_px": 3.0,
    "min_water_fraction": 0.3,
}
