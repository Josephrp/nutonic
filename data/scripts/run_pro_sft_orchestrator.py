#!/usr/bin/env python3
"""Run one or more PRO profile dataset builders with shared options."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent

BUILDERS = {
    "firewatch": _SCRIPTS / "build_lfm_vl_firewatch_sft.py",
    "oceanscout": _SCRIPTS / "build_lfm_vl_oceanscout_sft.py",
    "landshift": _SCRIPTS / "build_lfm_vl_landshift_sft.py",
    "floodpulse": _SCRIPTS / "build_lfm_vl_floodpulse_sft.py",
    "brief": _SCRIPTS / "build_lfm_vl_brief_sft.py",
}


def _run(cmd: list[str]) -> int:
    print(" ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return int(r.returncode)


def main() -> int:
    p = argparse.ArgumentParser(description="Run PRO mini-app SFT dataset builders.")
    p.add_argument(
        "--profiles",
        default="firewatch,oceanscout,landshift,floodpulse,brief",
        help="Comma-separated profile list (firewatch,oceanscout,landshift,floodpulse,brief).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "pro_sft",
        help="Root output directory. Each profile writes to a subdirectory.",
    )
    p.add_argument("--events-per-profile", type=int, default=50)
    p.add_argument("--fire-events", type=Path, default=None)
    p.add_argument("--flood-events", type=Path, default=None)
    p.add_argument("--land-events", type=Path, default=None)
    p.add_argument("--ocean-events", type=Path, default=None)
    p.add_argument("--ee-project", default=None, help="Accepted for compatibility; forwarded via env if needed.")
    p.add_argument("--max-cloud-pct", type=float, default=30.0)
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--hf-token", default=None)
    args = p.parse_args()

    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    wanted = [x.strip().lower() for x in args.profiles.split(",") if x.strip()]
    unknown = [w for w in wanted if w not in BUILDERS]
    if unknown:
        print(f"Unknown profiles: {', '.join(unknown)}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for prof in wanted:
        script = BUILDERS[prof]
        prof_out = out_root / f"{prof}_sft"
        prof_work = out_root / "_work" / f"{prof}_work"
        cmd = [sys.executable, str(script), "--out-dir", str(prof_out)]
        if prof != "brief":
            cmd.extend(["--work-dir", str(prof_work), "--max-cloud-pct", str(args.max_cloud_pct)])
        if prof in {"firewatch", "floodpulse"}:
            ev = args.fire_events if prof == "firewatch" else args.flood_events
            if ev is None:
                print(f"{prof} requires --{'fire-events' if prof == 'firewatch' else 'flood-events'}", file=sys.stderr)
                failures.append(f"{prof}: missing events file")
                continue
            cmd.extend(["--events", str(ev), "--max-events", str(args.events_per_profile)])
        elif prof == "landshift":
            if args.land_events is not None:
                cmd.extend(["--events", str(args.land_events)])
            cmd.extend(["--seeded-events", str(args.events_per_profile), "--max-events", str(args.events_per_profile)])
        elif prof == "oceanscout":
            if args.ocean_events is not None:
                cmd.extend(["--events", str(args.ocean_events)])
            cmd.extend(["--seeded-events", str(args.events_per_profile), "--max-events", str(args.events_per_profile)])
        elif prof == "brief":
            cmd.extend(
                [
                    "--samples",
                    str(max(100, args.events_per_profile * 10)),
                    "--source-root",
                    str(out_root / "firewatch_sft"),
                    "--source-root",
                    str(out_root / "oceanscout_sft"),
                    "--source-root",
                    str(out_root / "landshift_sft"),
                    "--source-root",
                    str(out_root / "floodpulse_sft"),
                ]
            )

        if args.no_upload:
            cmd.append("--no-upload")
        if args.hf_token:
            cmd.extend(["--hf-token", args.hf_token])
        rc = _run(cmd)
        if rc != 0:
            failures.append(f"{prof}: rc={rc}")

    if failures:
        print("PRO SFT orchestrator failures:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"Done. Outputs under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

