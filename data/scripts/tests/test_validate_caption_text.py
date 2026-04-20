from __future__ import annotations

from validate_hint_strings import Violation, validate_caption_text, violations_to_jsonable


def test_caption_ok() -> None:
    assert not validate_caption_text("Urban roadside scene with varied textures.", max_len=200)


def test_caption_rejects_coord_like_pair() -> None:
    bad = "Try near -33.8650, 151.2094 for context."
    v = validate_caption_text(bad, max_len=400)
    assert v and v[0].code == "coordinate_literal"


def test_caption_length() -> None:
    long = "x" * 500
    v = validate_caption_text(long, max_len=400)
    assert any(x.code == "length_cap" for x in v)


def test_violations_to_jsonable() -> None:
    rows = violations_to_jsonable(
        [Violation("length_cap", "too long", path="tier_1"), Violation("coordinate_literal", "pair", path="")]
    )
    assert rows == [
        {"code": "length_cap", "message": "too long", "path": "tier_1"},
        {"code": "coordinate_literal", "message": "pair", "path": ""},
    ]
