#!/usr/bin/env python3
"""
Poll Hugging Face Space runtime until Docker has finished building.

After ``hf upload``, the Space stays ``RUNNING`` on the old image briefly, then moves through
``BUILDING`` / ``RUNNING_BUILDING`` until the new image is ``RUNNING``. Waiting on the Hub API
avoids long blind sleeps in smoke tests (see ``live_inference_smoke.py`` retries).

Usage (repo root, token with Hub read access):

  export HF_TOKEN=...
  python tools/hf_deploy/wait_for_space_runtime.py --repo-id NuTonic/nutonic-pro-materialization
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ERROR_STAGES = frozenset({"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"})
ACTIVE_BUILD_STAGES = frozenset({"BUILDING", "RUNNING_BUILDING"})


def main() -> int:
    p = argparse.ArgumentParser(description="Wait until HF Space Docker build reaches stable RUNNING.")
    p.add_argument("--repo-id", required=True, help="e.g. NuTonic/nutonic-pro-materialization")
    p.add_argument("--token-env", default="HF_TOKEN", help="Env var holding Hub token (default: HF_TOKEN).")
    p.add_argument("--poll-interval", type=float, default=10.0, help="Seconds between API polls (default: 10).")
    p.add_argument(
        "--timeout-seconds",
        type=float,
        default=1200.0,
        help="Give up after this many seconds (default: 1200).",
    )
    p.add_argument(
        "--assume-ready-after-seconds",
        type=float,
        default=90.0,
        help=(
            "If stage stays RUNNING and we never see BUILDING/RUNNING_BUILDING (cache hit / no rebuild), "
            "exit successfully after this many seconds (default: 90)."
        ),
    )
    p.add_argument(
        "--running-stable-polls",
        type=int,
        default=2,
        help="Require this many consecutive RUNNING polls after a build was observed (default: 2).",
    )
    args = p.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(f"Missing {args.token_env} in environment.", file=sys.stderr)
        return 2

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    deadline = time.monotonic() + args.timeout_seconds
    saw_build = False
    consecutive_running = 0
    stable_need = max(1, args.running_stable_polls)
    t0 = time.monotonic()

    while time.monotonic() < deadline:
        rt = api.get_space_runtime(args.repo_id)
        stage = str(rt.stage)
        elapsed = time.monotonic() - t0

        if stage in ERROR_STAGES:
            print(f"[wait-space] stage={stage} — Space build/runtime failed.", file=sys.stderr)
            print(rt.raw, file=sys.stderr)
            return 1

        if stage in ACTIVE_BUILD_STAGES:
            saw_build = True
            consecutive_running = 0
            print(f"[wait-space] {elapsed:5.0f}s  stage={stage}")
        elif stage == "RUNNING":
            if saw_build:
                consecutive_running += 1
                print(f"[wait-space] {elapsed:5.0f}s  stage=RUNNING  ({consecutive_running}/{stable_need} stable)")
                if consecutive_running >= stable_need:
                    print("[wait-space] Build finished; Space is RUNNING.")
                    return 0
            else:
                print(f"[wait-space] {elapsed:5.0f}s  stage=RUNNING  (waiting for build signal…)")
                if elapsed >= args.assume_ready_after_seconds:
                    print(
                        "[wait-space] No BUILDING/RUNNING_BUILDING observed; treating as ready "
                        "(identical layers / fast path)."
                    )
                    return 0
                consecutive_running = 0
        else:
            consecutive_running = 0
            print(f"[wait-space] {elapsed:5.0f}s  stage={stage}")

        time.sleep(max(3.0, args.poll_interval))

    print(f"[wait-space] Timed out after {args.timeout_seconds:.0f}s.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
