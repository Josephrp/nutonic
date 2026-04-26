"""
Canonical Liquid AI Hugging Face model ids for NU:TONIC Jobs and batch scripts.

- **Text LFM** — narrative sidecar, vLLM autostart when ``NUTONIC_VLLM_MODEL`` is unset.
- **LFM-VL** — must match ``lfm_vl_hint_service`` / satellite caption defaults (Street View + imagery).
"""

DEFAULT_LFM_TEXT_HF_MODEL_ID = "LiquidAI/LFM2.5-1.2B-Instruct"
DEFAULT_LFM_VL_HF_MODEL_ID = "LiquidAI/LFM2.5-VL-450M"
