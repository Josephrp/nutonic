"""
One-off: example.imageviewer -> com.nutonic, example.map -> com.nutonic.map (IMP-020).
Run from repo root: python scripts/migrate_kmp_packages_once.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "nutonic"


def move_imageviewer_trees() -> int:
    n = 0
    for p in sorted(ROOT.rglob("imageviewer"), key=lambda x: len(str(x)), reverse=True):
        if not p.is_dir() or p.name != "imageviewer" or p.parent.name != "example":
            continue
        kotlin_dir = p.parent.parent
        dest = kotlin_dir / "com" / "nutonic"
        dest.mkdir(parents=True, exist_ok=True)
        for item in list(p.iterdir()):
            target = dest / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
        p.rmdir()
        ex = kotlin_dir / "example"
        if ex.is_dir() and not any(ex.iterdir()):
            ex.rmdir()
        n += 1
    return n


def move_map_trees() -> int:
    n = 0
    for p in sorted(ROOT.rglob("map"), key=lambda x: len(str(x)), reverse=True):
        if not p.is_dir() or p.name != "map" or p.parent.name != "example":
            continue
        rel = p.relative_to(ROOT)
        if "kotlin" not in rel.parts:
            continue
        kotlin_dir = p.parent.parent
        dest_root = kotlin_dir / "com" / "nutonic"
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / "map"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(p), str(dest))
        ex = kotlin_dir / "example"
        if ex.is_dir() and not any(ex.iterdir()):
            ex.rmdir()
        n += 1
    return n


def rewrite_sources() -> None:
    exts = {".kt", ".kts", ".xml", ".xcconfig", ".swift", ".properties"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        # Skip Gradle output trees only (never skip build.gradle.kts — that has no "build" path segment).
        if "build" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        text = text.replace("example.imageviewer.", "com.nutonic.")
        text = text.replace("example.imageviewer", "com.nutonic")
        text = text.replace("example.map.collection", "com.nutonic.map.collection")
        text = text.replace("example.map.", "com.nutonic.map.")
        text = text.replace("example.map", "com.nutonic.map")
        if text != orig:
            path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    if not ROOT.is_dir():
        print("Expected nutonic/ under repo root", file=sys.stderr)
        return 1
    a = move_imageviewer_trees()
    b = move_map_trees()
    rewrite_sources()
    print(f"moved imageviewer trees: {a}, map trees: {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
