from __future__ import annotations

from narrative_sidecar_postprocess import sidecar_postprocess_plaintext


def test_strip_bold_and_rules() -> None:
    raw = (
        "Intro line.\n\n---\n\n**End transmission.**\n"
        "More `code` and *italic* here.\n"
    )
    out = sidecar_postprocess_plaintext(raw)
    assert "**" not in out
    assert "---" not in out
    assert "`" not in out
    assert "End transmission." in out
    assert "code" in out


def test_strip_fenced_block() -> None:
    raw = "Hello\n```json\n{\"a\": 1}\n```\nTail"
    out = sidecar_postprocess_plaintext(raw)
    assert "```" not in out
    assert "Tail" in out


def test_strip_heading_and_list() -> None:
    raw = "## Title\n\n- first item\n* second\nBody."
    out = sidecar_postprocess_plaintext(raw)
    assert not out.startswith("#")
    assert "first item" in out
    assert "Body." in out


def test_empty() -> None:
    assert sidecar_postprocess_plaintext("") == ""
    assert sidecar_postprocess_plaintext("   ") == ""
