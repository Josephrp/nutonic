"""
Heuristic QA for LLM sector INTEL blurbs (gaming tone, anti-slop).

Used by ``narrative_llm_batch.py`` to flag weak copy and optionally trigger one rewrite pass.
No extra model load — pattern checks only.
"""

from __future__ import annotations

import re
from typing import Final

# Case-insensitive banned *sentence starters* (generic brochure / GeoGuessr-summary tone).
_BANNED_OPENER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*this\s+sector\s+(?:offers|presents|reveals|shows|provides)\b", re.I | re.M),
    re.compile(r"^\s*the\s+sector\s+(?:offers|presents|reveals|shows|provides)\b", re.I | re.M),
    re.compile(r"^\s*here\s+you\s+(?:can|will)\s+see\b", re.I | re.M),
    re.compile(r"^\s*in\s+this\s+sector\b", re.I | re.M),
)

# Lazy filler anywhere in the blurb.
_BANNED_PHRASE_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bperfect\s+for\s+(?:those|players|anyone|visitors|tourists)\b", re.I),
    re.compile(r"\bideal\s+for\s+(?:players|those|anyone)\b", re.I),
    re.compile(r"\bgreat\s+for\s+(?:players|those|anyone)\b", re.I),
    re.compile(r"\bbeautiful\s+(?:scenery|landscape|view)\b", re.I),
    re.compile(r"\bserene\s+(?:atmosphere|environment|setting)\b", re.I),
    re.compile(r"\btranquil\s+(?:atmosphere|landscape|setting)\b", re.I),
    re.compile(r"\btake\s+your\s+time\s+to\s+explore\b", re.I),
    re.compile(r"\bclear\s+understanding\s+of\s+this\s+zone\b", re.I),
)


def narrative_qa_violations(text: str) -> list[str]:
    """Return stable machine codes for each failed check (empty if clean)."""
    t = (text or "").strip()
    out: list[str] = []
    if len(t) < 40:
        out.append("too_short")
    for i, pat in enumerate(_BANNED_OPENER_PATTERNS):
        if pat.search(t):
            out.append(f"banned_opener_{i}")
            break
    for i, pat in enumerate(_BANNED_PHRASE_RES):
        if pat.search(t):
            out.append(f"banned_phrase_{i}")
    # Brochure triple: "offers" + "glimpse" + "landscape" in one short blurb is almost always slop.
    if re.search(r"\boffers\b", t, re.I) and re.search(r"\bglimpse\b", t, re.I) and re.search(
        r"\b(?:landscape|environment|setting)\b", t, re.I
    ):
        out.append("brochure_cluster_offers_glimpse_landscape")
    return out


def narrative_qa_rank_key(text: str) -> tuple[int, int]:
    """
    Sort key where **larger is better** (for ``max(..., key=…)``).

    First: opener must not match banned patterns.
    Second: fewer violation codes (including banned phrases).
    """
    viols = narrative_qa_violations(text)
    opener_bad = any(v.startswith("banned_opener_") for v in viols)
    return (0 if opener_bad else 1, -len(viols))


def narrative_qa_retry_user_suffix(violations: list[str]) -> str:
    """Append to the prompt for a single corrective regeneration."""
    if not violations:
        return ""
    human = []
    for v in violations[:6]:
        if v == "too_short":
            human.append("write at least two full sentences")
        elif v.startswith("banned_opener_"):
            human.append("do not begin with 'This sector…', 'The sector…', 'Here you can see…', or 'In this sector…'")
        elif v.startswith("banned_phrase_"):
            human.append("avoid brochure phrases like 'perfect for players', 'ideal for', 'serene atmosphere', 'take your time to explore'")
        elif v == "brochure_cluster_offers_glimpse_landscape":
            human.append("avoid stacking 'offers', 'glimpse', and 'landscape/environment' in one blurb")
        else:
            human.append(v)
    uniq: list[str] = []
    for x in human:
        if x not in uniq:
            uniq.append(x)
    joined = "; ".join(uniq)
    return (
        f"\n\n---\nEditor pass (same facts, new wording): your previous draft failed style checks ({joined}). "
        "Rewrite **only** the INTEL blurb: still 2–4 sentences, plain text, same constraints as above."
    )


def narrative_qa_should_regenerate(violations: list[str]) -> bool:
    """Whether a single retry is worth doing (conservative to limit extra GPU time)."""
    if not violations:
        return False
    if any(v.startswith("banned_opener_") for v in violations):
        return True
    if "too_short" in violations:
        return True
    # Two or more independent problems (e.g. two banned phrases).
    phrase_hits = sum(1 for v in violations if v.startswith("banned_phrase_"))
    if phrase_hits >= 2:
        return True
    if "brochure_cluster_offers_glimpse_landscape" in violations and phrase_hits >= 1:
        return True
    return False
