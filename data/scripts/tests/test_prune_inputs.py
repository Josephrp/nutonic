"""Tests for post-build pruning of heavy POI inputs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.prune_inputs import prune_sentinel_l2a


def test_prune_sentinel_removes_when_under_poi_root(tmp_path: Path) -> None:
    root = tmp_path / "merged"
    poi = root / "poi_0000"
    s2 = poi / "sentinel-2-l2a" / "S2X_1"
    s2.mkdir(parents=True)
    (s2 / "visual.tif").write_bytes(b"x")
    ok, reason = prune_sentinel_l2a(poi, root, allow_external=False)
    assert ok and reason == "removed"
    assert not (poi / "sentinel-2-l2a").exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX symlinks without admin")
def test_prune_sentinel_skips_when_sentinel_resolves_outside_poi_root(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical_poi"
    outside = canonical / "sentinel-2-l2a" / "item"
    outside.mkdir(parents=True)
    (outside / "a.tif").write_text("a", encoding="utf-8")

    merged = tmp_path / "merged"
    poi_link = merged / "poi_0000"
    poi_link.mkdir(parents=True)
    (poi_link / "sentinel-2-l2a").symlink_to(canonical / "sentinel-2-l2a", target_is_directory=True)

    ok, reason = prune_sentinel_l2a(poi_link, merged, allow_external=False)
    assert not ok
    assert reason == "skipped_resolves_outside_poi_root"
    assert outside.exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX symlinks without admin")
def test_prune_allow_external_deletes_resolved_target(tmp_path: Path) -> None:
    root = tmp_path / "merged"
    poi = root / "poi_0000"
    poi.mkdir(parents=True)
    ext = tmp_path / "external_poi" / "sentinel-2-l2a" / "x"
    ext.mkdir(parents=True)
    (ext / "f.tif").write_bytes(b"1")
    (poi / "sentinel-2-l2a").symlink_to(ext.parent.parent / "sentinel-2-l2a", target_is_directory=True)

    ok, reason = prune_sentinel_l2a(poi, root, allow_external=True)
    assert ok and reason == "removed"
    assert not ext.parent.exists()
    assert not (poi / "sentinel-2-l2a").exists()
