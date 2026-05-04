"""FastAPI surface for Hugging Face Docker / ZeroGPU deployment (not used by Kotlin clients directly)."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import Body, FastAPI, HTTPException

from nutonic_terramind_tim_local.spaces_zero import apply_zero_gpu
from nutonic_terramind_tim_local.terramind_patches import terramind_patch_diagnostics
from nutonic_terramind_tim_local.tim_defaults import DEFAULT_TIM_MODEL_ID

app = FastAPI(title="NU:TONIC TerraMind TiM local (Space)", version="0.1.0")


def _run_tim_export(cfg: dict[str, Any]) -> dict[str, Any]:
    from nutonic_terramind_tim_local.run import run_tim_forward_export

    return run_tim_forward_export(cfg)


_run_tim_export_gpu = apply_zero_gpu(_run_tim_export)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "terramind_tim_local",
        "space": True,
        "patch_diagnostics": terramind_patch_diagnostics(),
    }


@app.post("/v1/tim/export")
def tim_export(
    body: dict[str, Any] = Body(
        ...,
        examples=[
            {
                "config": {
                    "model_id": DEFAULT_TIM_MODEL_ID,
                    "pretrained": True,
                    "modalities": ["RGB"],
                    "tim_modalities": ["LULC", "location"],
                    "merge_method": "mean",
                    "device": "cpu",
                    "inputs": {"mode": "random", "batch_size": 1},
                    "serialization": {
                        "tensor_sample_limit": 0,
                        "encoder_tensor_sample_limit": 0,
                        "include_encoder_trace": True,
                        "encoder_trace_mode": "last",
                    },
                    "export": {
                        "map_id": "smoke_map",
                        "location_id": "smoke_loc",
                        "include_ai_guess_row": True,
                    },
                }
            },
        ],
    ),
) -> dict[str, Any]:
    """
    Run :func:`run_tim_forward_export` with a YAML-style mapping.

    Pass either ``{"config": {...}}`` or ``{"config_yaml": "<yaml string>"}``.
    Real GeoGuessr / S2 configs reference on-disk assets; use the CLI for full pipelines.
    """
    return _run_from_body(body)


@app.post("/v1/tim/infer")
def tim_infer(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    Profile-first alias for live PRO orchestration.

    Accepts the same payload as ``/v1/tim/export`` and may include a top-level
    ``profile`` / ``analysis_profile`` value, which is copied into the config.
    """
    return _run_from_body(body)


def _run_from_body(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    cfg: dict[str, Any] | None = None
    raw_yaml = body.get("config_yaml")
    if isinstance(raw_yaml, str) and raw_yaml.strip():
        loaded = yaml.safe_load(raw_yaml)
        if not isinstance(loaded, dict):
            raise HTTPException(status_code=400, detail="config_yaml root must be a mapping")
        cfg = loaded
    elif isinstance(body.get("config"), dict):
        cfg = body["config"]
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide 'config' (object) or 'config_yaml' (string)",
        )
    profile = body.get("profile") or body.get("analysis_profile")
    if isinstance(profile, str) and profile.strip():
        cfg = dict(cfg)
        cfg.setdefault("analysis_profile", profile.strip())

    try:
        return _run_tim_export_gpu(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
