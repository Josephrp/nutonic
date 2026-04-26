"""Plain-text cleanup for LLM narrative sidecars (no torch/transformers imports)."""

from __future__ import annotations

import re


def sidecar_postprocess_plaintext(s: str) -> str:
    """Strip common markdown / decorative markup from narrative sidecar text (keep prose)."""
    if not s:
        return ""
    t = s.strip()
    t = re.sub(r"```[^\n`]*\n([\s\S]*?)```", r"\1", t)
    t = re.sub(r"```([\s\S]*?)```", r"\1", t)
    t = re.sub(r"(?m)^\s*-{3,}\s*$", "", t)
    t = re.sub(r"\s-{3,}\s", " ", t)
    t = re.sub(r"(?m)^#+\s*", "", t)
    for _ in range(8):
        n = re.sub(r"\*\*([\s\S]*?)\*\*", r"\1", t, count=1)
        if n == t:
            break
        t = n
    t = re.sub(r"__([\s\S]*?)__", r"\1", t)
    t = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+)\*(?!\*)", r"\1", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
