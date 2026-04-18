from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_HFJ = Path(__file__).resolve().parents[1] / "hf_jobs"

if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

import pano_batch_env  # noqa: E402


def test_cli_extras_from_environ_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTONIC_SHUFFLE_SEED", "7")
    monkeypatch.setenv("NUTONIC_PANO_SAMPLING_MODE", "STOCHASTIC_S2_FOOTPRINT")
    monkeypatch.setenv("NUTONIC_PANO_AREA_RADIUS_M", "1500")
    extras = pano_batch_env.pano_batch_cli_extras_from_environ()
    assert "--shuffle-seed" in extras
    assert "7" in extras
    assert "--pano-sampling-mode" in extras
    assert "--pano-area-radius-m" in extras


def test_sv_job_env_from_argparse() -> None:
    ns = SimpleNamespace(
        shuffle_seed=99,
        pano_sampling_mode=" LEGACY_RADIAL_OFFSET ",
        pano_jitter_seed=None,
        pano_area_radius_m=None,
        pano_min_anchor_separation_m=None,
        pano_legacy_radius_m=None,
    )
    d = pano_batch_env.pano_sv_job_env_from_argparse(ns)
    assert d["NUTONIC_SHUFFLE_SEED"] == "99"
    assert d["NUTONIC_PANO_SAMPLING_MODE"] == "LEGACY_RADIAL_OFFSET"


def test_apply_pano_argparse_to_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NUTONIC_SHUFFLE_SEED", raising=False)
    ns = SimpleNamespace(
        shuffle_seed=1,
        pano_sampling_mode=None,
        pano_jitter_seed=None,
        pano_area_radius_m=None,
        pano_min_anchor_separation_m=None,
        pano_legacy_radius_m=None,
    )
    pano_batch_env.apply_pano_argparse_to_environ(ns)
    assert os.environ.get("NUTONIC_SHUFFLE_SEED") == "1"
