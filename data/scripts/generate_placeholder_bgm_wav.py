#!/usr/bin/env python3
"""Emit silent WAV placeholders under shared composeResources (`docs/SCREEN-MUSIC-SPEC.md` §4)."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

TRACK_IDS = [
    "music_splash",
    "music_auth",
    "music_role",
    "music_scan_hub",
    "music_gameplay",
    "music_success",
    "music_results",
    "music_intel",
    "music_rank",
    "music_setup",
    "music_pro",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "nutonic"
        / "shared"
        / "src"
        / "commonMain"
        / "composeResources"
        / "files"
        / "music",
    )
    p.add_argument("--sample-rate", type=int, default=8000)
    p.add_argument("--duration-sec", type=float, default=0.12)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    nframes = int(args.sample_rate * args.duration_sec)
    for tid in TRACK_IDS:
        path = args.out_dir / f"{tid}.wav"
        with wave.open(str(path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(args.sample_rate)
            w.writeframes(b"\x00\x00" * nframes)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
