from __future__ import annotations

from validate_hint_strings import validate_caption_text


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
