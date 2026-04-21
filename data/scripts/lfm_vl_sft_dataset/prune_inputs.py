"""Remove heavy per-POI download artifacts after a successful build step."""

from __future__ import annotations

import shutil
from pathlib import Path


def _resolved_is_descendant(path: Path, ancestor: Path) -> bool:
    """True if ``path.resolve()`` is ``ancestor`` or strictly inside it."""
    try:
        p = path.resolve()
        a = ancestor.resolve()
    except OSError:
        return False
    if p == a:
        return True
    try:
        p.relative_to(a)
        return True
    except ValueError:
        return False


def prune_sentinel_l2a(
    poi_dir: Path,
    poi_root: Path,
    *,
    allow_external: bool = False,
) -> tuple[bool, str]:
    """
    Remove ``<poi_dir>/sentinel-2-l2a`` to free disk after RGB/DW processing.

    By default, deletes the directory only if it **resolves** under ``poi_root``.
    Symlinks that jump outside ``poi_root`` are skipped (avoids deleting a shared
    canonical download when ``merged/poi_0000`` points at ``../source/poi_0000``).

    With ``allow_external=True``, resolves the real directory and removes that tree,
    then drops a dangling symlink if one was left at ``sentinel-2-l2a``.

    Returns ``(did_remove, reason)``.
    """
    s2 = poi_dir / "sentinel-2-l2a"
    if not s2.exists():
        return False, "no_sentinel_dir"
    target = s2.resolve()
    if not allow_external and not _resolved_is_descendant(target, poi_root):
        return False, "skipped_resolves_outside_poi_root"
    try:
        shutil.rmtree(target, ignore_errors=False)
        if s2.exists() and s2.is_symlink():
            s2.unlink(missing_ok=True)
        return True, "removed"
    except OSError as e:
        return False, f"rmtree_failed:{e}"


def prune_poi_mapbox_cache(poi_dir: Path, poi_root: Path, *, allow_external: bool = False) -> tuple[bool, str]:
    """Remove ``<poi_dir>/mapbox`` (GeoGuessr downloader cache) with same safety rules as Sentinel."""
    mb = poi_dir / "mapbox"
    if not mb.exists():
        return False, "no_mapbox_dir"
    target = mb.resolve()
    if not allow_external and not _resolved_is_descendant(target, poi_root):
        return False, "skipped_resolves_outside_poi_root"
    try:
        shutil.rmtree(target, ignore_errors=False)
        if mb.exists() and mb.is_symlink():
            mb.unlink(missing_ok=True)
        return True, "removed"
    except OSError as e:
        return False, f"rmtree_failed:{e}"
