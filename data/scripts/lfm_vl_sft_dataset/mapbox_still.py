"""Fetch Mapbox Satellite static still for POI context (same contract as download_geoguessr_poi_imagery)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_simsat_module():
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "download_simsat_sources.py"
    spec = importlib.util.spec_from_file_location("download_simsat_sources", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_mapbox_still_png(
    *,
    lat: float,
    lon: float,
    poi_id: str,
    dest_dir: Path,
    session: Any,
    token: str,
    zoom: float = 12.0,
    size: int = 1280,
    retina: bool = True,
) -> str:
    """
    Write ``mapbox_stills/{poi_id}.png`` under ``dest_dir``.

    Returns repo-relative style path: ``mapbox_stills/{poi_id}.png``.
    """
    simsat = _load_simsat_module()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{poi_id}.png"
    simsat.fetch_mapbox_static(
        session,
        token,
        lon,
        lat,
        zoom,
        0.0,
        0.0,
        size,
        size,
        retina,
        dest,
    )
    return f"mapbox_stills/{poi_id}.png"
