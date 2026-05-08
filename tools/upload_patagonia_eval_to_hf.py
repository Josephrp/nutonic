#!/usr/bin/env python3
"""
Upload Patagonia eval output to a Hugging Face **dataset** repository.

Uploads the full run folder, and when ``models/<name>/`` exists (finetune vs base splits),
also uploads each subfolder to ``<run>/by_model/<name>/`` so both model outputs are easy to browse.

Runs may include ``gold/*.json`` sidecars (SCL fractions, optional Dynamic World fetch metadata from
``evaluate_vlm_patagonia_tim_e2e.py``); upload preserves the full tree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path


def upload_patagonia_eval_bundle(
    *,
    folder: Path,
    repo_id: str,
    path_in_repo: str | None = None,
    token: str | None = None,
    private: bool = False,
    skip_create_repo: bool = False,
    upload_per_model_subfolders: bool = True,
) -> list[str]:
    """
    Upload ``folder`` to ``hf://datasets/{repo_id}/{path_in_repo}``.

    When ``folder/models/<role>/`` exists and ``upload_per_model_subfolders`` is True, also uploads
    each role directory to ``.../by_model/<role>/``.

    Returns hub URLs printed for logs (strings).
    """
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install huggingface_hub: pip install huggingface_hub") from exc

    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    tok = (token or "").strip() or None
    api = HfApi(token=tok)

    root = (path_in_repo or "").strip()
    if not root:
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        root = f"patagonia_eval_runs/{ts}"

    if not skip_create_repo:
        api.create_repo(
            repo_id=repo_id,
            repo_type="dataset",
            private=bool(private),
            exist_ok=True,
        )

    out_urls: list[str] = []

    api.upload_folder(
        folder_path=str(folder),
        repo_id=repo_id,
        repo_type="dataset",
        path_in_repo=root,
    )
    out_urls.append(f"hf://datasets/{repo_id}/{root}")

    models_dir = folder / "models"
    if upload_per_model_subfolders and models_dir.is_dir():
        for sub in sorted(models_dir.iterdir()):
            if not sub.is_dir():
                continue
            dest = f"{root}/by_model/{sub.name}"
            api.upload_folder(
                folder_path=str(sub),
                repo_id=repo_id,
                repo_type="dataset",
                path_in_repo=dest,
            )
            out_urls.append(f"hf://datasets/{repo_id}/{dest}")

    return out_urls


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--repo-id", required=True, help="Target dataset repo id, e.g. my-org/nutonic-patagonia-evals")
    p.add_argument(
        "--folder",
        type=Path,
        required=True,
        help="Local eval output directory (contains report.json, images/, models/, …)",
    )
    p.add_argument(
        "--path-in-repo",
        default="",
        help="Subfolder in the dataset repo. Default: patagonia_eval_runs/<UTC timestamp>.",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or "",
        help="Hub token (default: HF_TOKEN / HUGGINGFACE_HUB_TOKEN).",
    )
    p.add_argument(
        "--private",
        action="store_true",
        help="If the dataset repo must be created, create it as private (default: public).",
    )
    p.add_argument(
        "--skip-create-repo",
        action="store_true",
        help="Do not call create_repo; fail if the dataset does not exist.",
    )
    p.add_argument(
        "--no-by-model-uploads",
        action="store_true",
        help="Do not upload separate copies under by_model/<name>/ (full tree only).",
    )
    args = p.parse_args(argv)

    token = (args.token or "").strip() or None
    urls = upload_patagonia_eval_bundle(
        folder=args.folder,
        repo_id=args.repo_id,
        path_in_repo=args.path_in_repo or None,
        token=token,
        private=bool(args.private),
        skip_create_repo=bool(args.skip_create_repo),
        upload_per_model_subfolders=not bool(args.no_by_model_uploads),
    )
    for u in urls:
        print(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
