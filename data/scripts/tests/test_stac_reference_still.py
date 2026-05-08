from __future__ import annotations

from stac_reference_still import bbox_around_point, resolve_href


def test_resolve_href_sentinel_bucket() -> None:
    h = "s3://sentinel-s2-l2a/tiles/1/C/DL/foo.tif"
    out = resolve_href(h)
    assert out.startswith("https://sentinel-s2-l2a.s3.eu-central-1.amazonaws.com/")


def test_bbox_around_point_symmetric() -> None:
    w, s, e, n = bbox_around_point(2.3, 48.9, 10.0)
    assert w < 2.3 < e and s < 48.9 < n
