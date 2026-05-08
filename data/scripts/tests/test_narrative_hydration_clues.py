"""Tests for narrative prompt clue extraction from streetview JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from narrative_hydration_clues import hydration_clues_for_narrative_prompt


def test_hydration_clues_prefers_assist_narrative_and_satellite() -> None:
    doc = {
        "streetview_assist_narrative": "  Assist line about curbs.  ",
        "streetview_hint_pack": [{"text": "Pack rank1", "viewpoint_id": "a", "rank": 1}],
        "satellite_caption_sidecar": {"caption": "  From above: roofs and trees.  "},
    }
    s, t = hydration_clues_for_narrative_prompt(doc)
    assert s == "Assist line about curbs."
    assert t == "From above: roofs and trees."


def test_hydration_clues_fallback_to_first_pack_text() -> None:
    doc = {
        "streetview_hint_pack": [
            {"text": "", "viewpoint_id": "a", "rank": 1},
            {"text": "First non-empty pack line.", "viewpoint_id": "b", "rank": 2},
        ],
    }
    s, t = hydration_clues_for_narrative_prompt(doc)
    assert "First non-empty pack line." in s
    assert "no satellite caption" in t.lower()


def test_hydration_clues_none_doc() -> None:
    s, t = hydration_clues_for_narrative_prompt(None)
    assert "streetview" in s.lower() or "generic" in s.lower()
    assert "satellite" in t.lower() or "vague" in t.lower()


def test_hydration_clues_long_pack_respects_budget() -> None:
    sentences = [f"Chunk {i} shows brick facades and curb lines." for i in range(40)]
    long = " ".join(sentences)
    doc = {"streetview_hint_pack": [{"text": long, "viewpoint_id": "a", "rank": 1}]}
    s, t = hydration_clues_for_narrative_prompt(doc, street_budget=260, sat_budget=None)
    assert "Chunk 0" in s
    assert len(s) <= 320
    assert "Chunk 25" not in s


def test_fixture_asm_fix_a_json(tmp_path: Path) -> None:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "assemble_manifest"
        / "streetview"
        / "asm_fix_a.json"
    )
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    s, t = hydration_clues_for_narrative_prompt(doc)
    assert "Street-level rhythm" in s
    assert "Ortho still" in t
