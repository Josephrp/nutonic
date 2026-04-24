#!/usr/bin/env python3
"""Run one or more PRO profile dataset builders with shared options."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent

_DEFAULT_FIRE_EVENTS = REPO_ROOT / "data" / "events" / "fire_smoke_events.json"
_DEFAULT_FLOOD_EVENTS = REPO_ROOT / "data" / "events" / "flood_smoke_events.json"
_DEFAULT_BRIEF_SAMPLES_FULL = 3000

_EVENTS_MISSING_HINT = (
    "Event JSON fixtures live under data/events/ (e.g. fire_smoke_events.json). "
    "If you cloned before they were tracked, run git pull, or copy the files in, "
    "or pass --fire-events / --flood-events explicitly."
)

# Dataset repo name suffixes (must match each builder's DEFAULT_HF_REPO ``org/name`` tail).
_PROFILE_HF_REPO_SUFFIX = {
    "firewatch": "firewatch-sft-v1",
    "oceanscout": "oceanscout-sft-v1",
    "landshift": "landshift-sft-v1",
    "floodpulse": "floodpulse-sft-v1",
    "brief": "brief-composer-sft-v1",
}

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
    p = argparse.ArgumentParser(
        description="Run PRO mini-app SFT dataset builders.",
        epilog=(
            "Tip: use --events-per-profile 0 to process every row in the events file(s) "
            "(--max-events 0 on each builder). Brief --samples defaults to "
            f"{_DEFAULT_BRIEF_SAMPLES_FULL} in that mode unless --brief-samples is set."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    p.add_argument(
        "--events-per-profile",
        type=int,
        default=50,
        help="Cap events per profile (passed as --max-events / --seeded-events). "
        "Use 0 for no cap: all rows in fire/flood JSON, all seeded land/ocean hubs, "
        "and Brief samples from --brief-samples or a full-run default.",
    )
    p.add_argument(
        "--fire-events",
        type=Path,
        default=_DEFAULT_FIRE_EVENTS,
        help=f"FireWatch events JSON/CSV (default: {_DEFAULT_FIRE_EVENTS.relative_to(REPO_ROOT)}).",
    )
    p.add_argument(
        "--flood-events",
        type=Path,
        default=_DEFAULT_FLOOD_EVENTS,
        help=f"FloodPulse events JSON/CSV (default: {_DEFAULT_FLOOD_EVENTS.relative_to(REPO_ROOT)}).",
    )
    p.add_argument("--land-events", type=Path, default=None)
    p.add_argument("--ocean-events", type=Path, default=None)
    p.add_argument("--ee-project", default=None, help="Accepted for compatibility; forwarded via env if needed.")
    p.add_argument("--max-cloud-pct", type=float, default=30.0)
    p.add_argument(
        "--brief-samples",
        type=int,
        default=None,
        help="BriefComposer --samples (overrides events-per-profile-based default).",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Forward --skip-existing to temporal builders (resume-friendly STAC cache).",
    )
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--hf-token", default=None)
    p.add_argument(
        "--hf-org",
        default=None,
        metavar="ORG_OR_USER",
        help="Hugging Face namespace for Hub uploads: uploads go to ORG/<default-repo-name> "
        f"(e.g. ORG/{_PROFILE_HF_REPO_SUFFIX['firewatch']}). "
        "Per-profile --upload-repo-* overrides this for that profile only.",
    )
    for _prof, _suffix in _PROFILE_HF_REPO_SUFFIX.items():
        p.add_argument(
            f"--upload-repo-{_prof}",
            dest=f"upload_repo_{_prof}",
            default=None,
            metavar="ORG/REPO",
            help=f"Full dataset repo id for {_prof} (passed as --upload-repo to that builder).",
        )
    args = p.parse_args()

    if args.ee_project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", args.ee_project)

    unlimited = args.events_per_profile <= 0
    max_events_arg = "0" if unlimited else str(args.events_per_profile)
    seeded_arg = "999" if unlimited else str(args.events_per_profile)
    if args.brief_samples is not None:
        brief_samples = args.brief_samples
    elif unlimited:
        brief_samples = _DEFAULT_BRIEF_SAMPLES_FULL
    else:
        brief_samples = max(100, args.events_per_profile * 10)

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
            if args.skip_existing:
                cmd.append("--skip-existing")
        if prof in {"firewatch", "floodpulse"}:
            ev = args.fire_events if prof == "firewatch" else args.flood_events
            ev = ev.resolve()
            if not ev.is_file():
                print(f"{prof}: events file not found: {ev}", file=sys.stderr)
                print(f"  {_EVENTS_MISSING_HINT}", file=sys.stderr)
                failures.append(f"{prof}: missing events file")
                continue
            cmd.extend(["--events", str(ev), "--max-events", max_events_arg])
        elif prof == "landshift":
            if args.land_events is not None:
                le = args.land_events.resolve()
                if not le.is_file():
                    print(f"{prof}: land events file not found: {le}", file=sys.stderr)
                    failures.append(f"{prof}: missing land events file")
                    continue
                cmd.extend(["--events", str(le)])
            else:
                cmd.extend(["--seeded-events", seeded_arg])
            cmd.extend(["--max-events", max_events_arg])
        elif prof == "oceanscout":
            if args.ocean_events is not None:
                oe = args.ocean_events.resolve()
                if not oe.is_file():
                    print(f"{prof}: ocean events file not found: {oe}", file=sys.stderr)
                    failures.append(f"{prof}: missing ocean events file")
                    continue
                cmd.extend(["--events", str(oe)])
            else:
                cmd.extend(["--seeded-events", seeded_arg])
            cmd.extend(["--max-events", max_events_arg])
        elif prof == "brief":
            cmd.extend(
                [
                    "--samples",
                    str(brief_samples),
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
        else:
            explicit_repo = getattr(args, f"upload_repo_{prof}", None)
            if explicit_repo:
                cmd.extend(["--upload-repo", str(explicit_repo).strip()])
            elif (args.hf_org or "").strip():
                ns = str(args.hf_org).strip().strip("/")
                suffix = _PROFILE_HF_REPO_SUFFIX[prof]
                cmd.extend(["--upload-repo", f"{ns}/{suffix}"])
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

