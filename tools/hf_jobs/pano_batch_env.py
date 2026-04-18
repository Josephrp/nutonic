"""
Street View batch / pano worker tuning via environment (Hugging Face Jobs + local hydration).

``batch_streetview_hints.py`` flags are derived here so ``entrypoint_hf_hydration.py`` and
``run_local_full_hydration.py`` stay in sync.

Environment → ``batch_streetview_hints`` CLI
---------------------------------------------
``NUTONIC_SHUFFLE_SEED``            → ``--shuffle-seed`` (catalog order + per-POI jitter derivation)
``NUTONIC_PANO_SAMPLING_MODE``      → ``--pano-sampling-mode`` (e.g. ``STOCHASTIC_S2_FOOTPRINT``)
``NUTONIC_PANO_JITTER_SEED``      → ``--pano-jitter-seed`` (fixed seed for every POI)
``NUTONIC_PANO_AREA_RADIUS_M``    → ``--pano-area-radius-m``
``NUTONIC_PANO_MIN_ANCHOR_SEPARATION_M`` → ``--pano-min-anchor-separation-m``
``NUTONIC_PANO_LEGACY_RADIUS_M``  → ``--pano-legacy-radius-m`` (legacy mode only)

Pano **uvicorn** subprocess (optional pass-through if set in the container)
--------------------------------------------------------------------------
``STREETVIEW_S2_GSD_M``, ``STREETVIEW_S2_CHIP_EDGE_PX``, ``STREETVIEW_EXPOSE_SAMPLING_DEBUG``
"""

from __future__ import annotations

import os
from typing import Any


def pano_batch_cli_extras_from_environ() -> list[str]:
    """Build extra argv fragments for ``python tools/batch_streetview_hints.py``."""
    out: list[str] = []

    sm = os.environ.get("NUTONIC_PANO_SAMPLING_MODE", "").strip()
    if sm:
        out += ["--pano-sampling-mode", sm]

    for env_key, flag in (
        ("NUTONIC_PANO_JITTER_SEED", "--pano-jitter-seed"),
        ("NUTONIC_SHUFFLE_SEED", "--shuffle-seed"),
    ):
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        try:
            int(raw)
        except ValueError:
            continue
        out += [flag, raw]

    for env_key, flag in (
        ("NUTONIC_PANO_AREA_RADIUS_M", "--pano-area-radius-m"),
        ("NUTONIC_PANO_MIN_ANCHOR_SEPARATION_M", "--pano-min-anchor-separation-m"),
        ("NUTONIC_PANO_LEGACY_RADIUS_M", "--pano-legacy-radius-m"),
    ):
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        try:
            float(raw)
        except ValueError:
            continue
        out += [flag, raw]

    return out


def pano_service_env_pass_through() -> dict[str, str]:
    """Subset of ``os.environ`` to merge into the pano worker process."""
    keys = (
        "STREETVIEW_S2_GSD_M",
        "STREETVIEW_S2_CHIP_EDGE_PX",
        "STREETVIEW_EXPOSE_SAMPLING_DEBUG",
    )
    return {k: os.environ[k].strip() for k in keys if os.environ.get(k, "").strip()}


def apply_pano_argparse_to_environ(ns: Any) -> None:
    """Copy non-empty pano-related CLI fields from ``ns`` into ``os.environ`` (local runners)."""
    for k, v in pano_sv_job_env_from_argparse(ns).items():
        os.environ[k] = v


def pano_sv_job_env_from_argparse(ns: Any) -> dict[str, str]:
    """Optional CLI on ``run_hf_hydration_full`` → Job env for **sv-lfm** only."""
    m: dict[str, str] = {}
    if getattr(ns, "shuffle_seed", None) is not None:
        m["NUTONIC_SHUFFLE_SEED"] = str(int(ns.shuffle_seed))
    pm = getattr(ns, "pano_sampling_mode", None)
    if pm is not None and str(pm).strip():
        m["NUTONIC_PANO_SAMPLING_MODE"] = str(pm).strip()
    if getattr(ns, "pano_jitter_seed", None) is not None:
        m["NUTONIC_PANO_JITTER_SEED"] = str(int(ns.pano_jitter_seed))
    if getattr(ns, "pano_area_radius_m", None) is not None:
        m["NUTONIC_PANO_AREA_RADIUS_M"] = str(float(ns.pano_area_radius_m))
    if getattr(ns, "pano_min_anchor_separation_m", None) is not None:
        m["NUTONIC_PANO_MIN_ANCHOR_SEPARATION_M"] = str(float(ns.pano_min_anchor_separation_m))
    if getattr(ns, "pano_legacy_radius_m", None) is not None:
        m["NUTONIC_PANO_LEGACY_RADIUS_M"] = str(float(ns.pano_legacy_radius_m))
    return m
