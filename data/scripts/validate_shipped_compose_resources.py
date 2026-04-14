#!/usr/bin/env python3
"""
Verify ``manifest.full.json`` still_bundled_resource paths exist under composeResources/.

Paths in the manifest are Compose Multiplatform resource paths (e.g. ``files/3.jpg``)
relative to the ``composeResources`` directory, not relative to ``composeResources/files``.

Used by Gradle ``:shared:validateCatalog`` (see docs/scripts/SPEC-catalog-lint.md §Related).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "nutonic"
    / "shared"
    / "src"
    / "commonMain"
    / "composeResources"
    / "files"
    / "cache"
    / "manifest.full.json"
)
DEFAULT_COMPOSE_RESOURCES_ROOT = (
    REPO_ROOT / "nutonic" / "shared" / "src" / "commonMain" / "composeResources"
)

EXIT_MISSING = 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate manifest still paths under composeResources/")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument(
        "--compose-resources-root",
        type=Path,
        default=DEFAULT_COMPOSE_RESOURCES_ROOT,
        help="Directory that contains files/… (Compose composeResources root).",
    )
    args = p.parse_args(argv)
    if not args.manifest.is_file():
        print(f"Missing manifest: {args.manifest}", file=sys.stderr)
        return EXIT_MISSING
    doc = json.loads(args.manifest.read_text(encoding="utf-8"))
    locs = doc.get("locations") or []
    if not isinstance(locs, list):
        print("manifest.locations must be a list", file=sys.stderr)
        return EXIT_MISSING
    missing: list[str] = []
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        rel = loc.get("still_bundled_resource")
        if not rel:
            continue
        root = args.compose_resources_root.resolve()
        path = (root / str(rel)).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            missing.append(f"path traversal rejected: {rel!r}")
            continue
        if not path.is_file():
            missing.append(f"missing file for still_bundled_resource={rel!r} -> {path}")
    if missing:
        for m in missing:
            print(m, file=sys.stderr)
        return EXIT_MISSING
    print("validate_shipped_compose_resources: ok", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
