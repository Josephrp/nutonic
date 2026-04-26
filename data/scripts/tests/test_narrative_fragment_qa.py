"""Tests for narrative INTEL blurb QA heuristics."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from narrative_fragment_qa import (
    narrative_qa_rank_key,
    narrative_qa_retry_user_suffix,
    narrative_qa_should_regenerate,
    narrative_qa_violations,
)


def test_qa_flags_banned_opener() -> None:
    t = "This sector offers a quiet glimpse into a rural mountain landscape."
    v = narrative_qa_violations(t)
    assert any(x.startswith("banned_opener_") for x in v)
    assert narrative_qa_should_regenerate(v) is True


def test_qa_flags_brochure_phrase() -> None:
    t = "Your uplink tags a memory fragment. The rows are perfect for players seeking calm."
    v = narrative_qa_violations(t)
    assert any(x.startswith("banned_phrase_") for x in v)


def test_qa_clean_intel_style() -> None:
    t = (
        "Your uplink stitches a stale corridor: white lane paint, a median strip, and heat shimmer off asphalt. "
        "From above the block reads like a tidy circuit—good for calibration, boring for bragging. "
        "Log it and move; the still is the real witness."
    )
    assert narrative_qa_violations(t) == []


def test_rank_key_prefers_no_opener_violation() -> None:
    bad = "This sector reveals a quiet road."
    good = "You get curb grass, a dented guardrail, and a sky washed gray—nothing heroic, just a place to remember."
    assert narrative_qa_rank_key(good) > narrative_qa_rank_key(bad)


def test_retry_suffix_non_empty() -> None:
    s = narrative_qa_retry_user_suffix(["banned_opener_0", "banned_phrase_0"])
    assert "Editor pass" in s
    assert "This sector" in s


def test_too_short_triggers_regenerate() -> None:
    v = narrative_qa_violations("Hi.")
    assert "too_short" in v
    assert narrative_qa_should_regenerate(v) is True
