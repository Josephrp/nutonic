"""
Forward host-exported inference tuning into Hugging Face Job ``env`` dicts.

Used by ``run_hf_hydration_full.py`` so operators can ``export LFM_VL_BACKEND=…``
before submit without editing Python.
"""

from __future__ import annotations

import os


_LFM_VL_HINT_KEYS = (
    "LFM_VL_BACKEND",
    "LFM_VL_MODEL_ID",
    "LFM_VL_REVISION",
    "LFM_OPENAI_BASE_URL",
    "LFM_OPENAI_API_KEY",
    "LFM_OPENAI_MODEL",
    "LFM_VL_MAX_NEW_TOKENS",
    "LFM_VL_TORCH_DTYPE",
    "LFM_VL_EAGER_LOAD",
)

_NARRATIVE_LLM_KEYS = (
    "NUTONIC_NARRATIVE_BACKEND",
    "NUTONIC_VLLM_MODEL",
    "NUTONIC_VLLM_PORT",
    "NUTONIC_VLLM_AUTOSTART",
    "NUTONIC_VLLM_EXTRA_ARGS",
    "NUTONIC_VLLM_SERVE_CMD",
    "NUTONIC_VLLM_BASE",
    "NUTONIC_NARRATIVE_OPENAI_BASE",
    "NUTONIC_NARRATIVE_OPENAI_MODEL",
    "NUTONIC_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "NUTONIC_NARRATIVE_TRANSFORMERS_MODEL",
    "NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW",
    "NUTONIC_OLLAMA_MODEL",
    "NUTONIC_OLLAMA_PULL",
    "NUTONIC_OLLAMA_READY_SEC",
    "NUTONIC_NARRATIVE_ENTRY_MAX",
    "OLLAMA_HOST",
)


def lfm_vl_hint_env_from_environ() -> dict[str, str]:
    """Non-secret LFM-VL hint service env vars to merge into the **sv-lfm** Job."""
    return {k: os.environ[k].strip() for k in _LFM_VL_HINT_KEYS if os.environ.get(k, "").strip()}


def narrative_llm_job_env_from_environ() -> dict[str, str]:
    """Narrative / vLLM / Ollama-related env vars to merge into the **llm-sidecars** Job."""
    return {k: os.environ[k].strip() for k in _NARRATIVE_LLM_KEYS if os.environ.get(k, "").strip()}


def geo_pipeline_env_from_environ() -> dict[str, str]:
    """Geo / useful-hints pipeline (sv-lfm). Forward ``NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL`` including ``0``."""
    k = "NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL"
    if k not in os.environ:
        return {}
    return {k: os.environ[k].strip()}
