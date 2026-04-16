#!/usr/bin/env python3
"""
Canonical **full** cache hydration: **Hugging Face Jobs only** (no local LFM-VL weight load).

Wraps ``run_hf_hydration_full.py``, which submits **three** Jobs in order: GPU ``sv-lfm``,
GPU TerraMind ``tim`` (STAC batch + upload), then CPU ``llm-sidecars``, waits, and downloads artifacts.

Build images first (from repo root)::

    python tools/hf_jobs/build_and_push_images.py --namespace YOUR_DOCKERHUB_USER --tag 2026-04-16

Example submit (full catalog + geo)::

    python tools/run_full_hydration.py --content-version my-run-2026-04-16 \\
      --sv-image YOUR_DOCKERHUB/nutonic-hydration-sv-lfm:TAG \\
      --tim-image YOUR_DOCKERHUB/nutonic-hydration-tim:TAG \\
      --llm-image YOUR_DOCKERHUB/nutonic-hydration-llm:TAG

First **five** ``geoguessr_poi_12`` POIs only (single-tree import; TiM uses ``first5`` YAML), skipping fragile geo/hints::

    python tools/run_full_hydration.py --content-version my-run-5poi \\
      --poi-limit 5 --skip-geo-hints \\
      --sv-image ... --tim-image ... --llm-image ...

Use ``--skip-tim`` only if you intentionally omit the TiM job. See ``tools/hf_jobs/README.md`` for ``.env`` keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from run_hf_hydration_full import main

if __name__ == "__main__":
    raise SystemExit(main())
