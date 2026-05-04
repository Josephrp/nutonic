#!/usr/bin/env python3
"""Stage a PRO VLM model bundle for publish-time packaging without Git LFS.

Inputs are environment-driven so GitHub Actions can source the model from a
release/CDN/Hub resolve URL or from an already checked-out local path.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

# Pin revision so CI/package hashes stay aligned with server defaults in `nutonic_server/settings.py`.
DEFAULT_PRO_VLM_MODEL_SOURCE_URL = (
    "https://huggingface.co/NuTonic/lspace/resolve/"
    "3ec756bfc8a94fcb23801fe6925d832ab35595f2/model.safetensors"
)


def main() -> int:
    p = argparse.ArgumentParser(description="Stage PRO VLM model bundle for the game-server Space image.")
    p.add_argument("--output", default="server/pro_vlm_bundles/pro-vlm.bin")
    p.add_argument("--source-url-env", default="NUTONIC_PRO_VLM_MODEL_SOURCE_URL")
    p.add_argument("--source-path-env", default="NUTONIC_PRO_VLM_MODEL_SOURCE_PATH")
    p.add_argument("--expected-sha-env", default="NUTONIC_PRO_VLM_MODEL_EXPECTED_SHA256")
    p.add_argument("--required", action="store_true")
    args = p.parse_args()

    source_url = os.environ.get(args.source_url_env, "").strip() or DEFAULT_PRO_VLM_MODEL_SOURCE_URL
    source_path = os.environ.get(args.source_path_env, "").strip()
    expected_sha = os.environ.get(args.expected_sha_env, "").strip().lower()
    out = Path(args.output)

    if not source_url and not source_path:
        if args.required:
            raise SystemExit(f"Missing {args.source_url_env} or {args.source_path_env}")
        print("No PRO VLM bundle source configured; skipping bundle staging.")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    if source_path:
        src = Path(source_path)
        if not src.is_file():
            raise SystemExit(f"Configured model source path does not exist: {src}")
        shutil.copyfile(src, out)
    else:
        req = Request(source_url, headers={"User-Agent": "NuTonic-pro-vlm-stage/1.0"})
        with urlopen(req, timeout=600) as response, out.open("wb") as f:
            shutil.copyfileobj(response, f)

    sha = _sha256_file(out)
    if expected_sha and sha != expected_sha:
        out.unlink(missing_ok=True)
        raise SystemExit(f"PRO VLM bundle sha256 mismatch: expected {expected_sha}, got {sha}")
    print(f"Staged PRO VLM bundle: {out} ({out.stat().st_size} bytes, sha256={sha})")
    return 0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
