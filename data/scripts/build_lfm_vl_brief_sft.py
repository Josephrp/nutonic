#!/usr/bin/env python3
"""Build BriefComposer SFT dataset by composing findings from profile datasets."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.caption_rules import brief_caption
from lfm_vl_sft_dataset.hf_upload import upload_dataset_folder
from lfm_vl_sft_dataset.jsonl_format import make_multi_image_vlm_message, split_key, write_jsonl
from lfm_vl_sft_dataset.pro_prompts import BRIEF_COMPOSER_PROMPT, SYSTEM_GEOSPATIAL_ANALYST, SYSTEM_OPTICAL_LIMITS

DEFAULT_HF_REPO = "NuTonic/brief-composer-sft-v1"


def _discover_metadata_files(root: Path) -> list[Path]:
    md = root / "metadata"
    if not md.is_dir():
        return []
    return sorted(md.glob("*.json"))


def _profile_from_meta(obj: dict, source_root: Path) -> str:
    p = obj.get("profile")
    if isinstance(p, str) and p:
        return p
    name = source_root.name.lower()
    if "fire" in name:
        return "firewatch"
    if "ocean" in name or "maritime" in name:
        return "oceanscout"
    if "land" in name:
        return "landshift"
    if "flood" in name:
        return "floodpulse"
    return "profile"


def _build_headline(meta: dict) -> str:
    profile = str(meta.get("profile", "profile"))
    n_regions = len(meta.get("regions", [])) if isinstance(meta.get("regions"), list) else 0
    if n_regions > 0:
        return f"{n_regions} localized region(s) identified in {profile} analysis"
    return f"No dominant localized regions in {profile} analysis"


def main() -> int:
    p = argparse.ArgumentParser(description="Build BriefComposer SFT dataset from profile dataset outputs.")
    p.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Profile dataset root containing images/ and metadata/. Repeatable.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "brief_composer_sft",
    )
    p.add_argument("--samples", type=int, default=1000)
    p.add_argument("--min-images", type=int, default=1)
    p.add_argument("--max-images", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--upload-repo", default=DEFAULT_HF_REPO)
    p.add_argument("--hf-token", default=None)
    p.add_argument("--private-repo", action="store_true")
    args = p.parse_args()

    roots = [Path(r).resolve() for r in args.source_root] if args.source_root else [
        (REPO_ROOT / "data" / "downloads" / "firewatch_sft").resolve(),
        (REPO_ROOT / "data" / "downloads" / "oceanscout_sft").resolve(),
        (REPO_ROOT / "data" / "downloads" / "landshift_sft").resolve(),
        (REPO_ROOT / "data" / "downloads" / "floodpulse_sft").resolve(),
    ]
    candidates: list[dict] = []
    for root in roots:
        for mf in _discover_metadata_files(root):
            try:
                obj = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            stem = mf.stem
            img_dir = root / "images"
            img_paths = sorted(img_dir.glob(f"{stem}*.png"))
            if not img_paths:
                continue
            profile = _profile_from_meta(obj, root)
            candidates.append(
                {
                    "source_root": root,
                    "profile": profile,
                    "meta": obj,
                    "stem": stem,
                    "images": img_paths,
                }
            )
    if not candidates:
        print("No source profile metadata/images found. Pass --source-root paths.", file=sys.stderr)
        return 2

    out_dir = args.out_dir.resolve()
    images_out = out_dir / "images"
    data_out = out_dir / "data"
    metadata_out = out_dir / "metadata"
    images_out.mkdir(parents=True, exist_ok=True)
    data_out.mkdir(parents=True, exist_ok=True)
    metadata_out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    by_split: dict[str, list[dict]] = defaultdict(list)
    sample_count = max(0, int(args.samples))
    min_images = max(1, int(args.min_images))
    max_images = max(min_images, int(args.max_images))
    for i in range(sample_count):
        take = rng.randint(min_images, max_images)
        picks = rng.sample(candidates, k=min(take, len(candidates)))
        copied_rel_images: list[str] = []
        findings: list[dict] = []
        profile_mix: list[str] = []
        for j, pck in enumerate(picks):
            profile = str(pck["profile"])
            profile_mix.append(profile)
            img = rng.choice(pck["images"])
            dst_name = f"brief_{i:06d}_{j:02d}_{profile}_{img.name}"
            dst = images_out / dst_name
            shutil.copy2(img, dst)
            copied_rel_images.append(f"images/{dst_name}")
            findings.append(
                {
                    "profile": profile,
                    "headline": _build_headline(pck["meta"]),
                    "source_stem": pck["stem"],
                }
            )

        assistant = brief_caption(findings, profile_mix)
        row = make_multi_image_vlm_message(
            copied_rel_images,
            BRIEF_COMPOSER_PROMPT,
            assistant,
            system_text=f"{SYSTEM_GEOSPATIAL_ANALYST} {SYSTEM_OPTICAL_LIMITS}",
            metadata={"sample_id": f"brief_{i:06d}", "profiles": profile_mix},
        )
        split = split_key(f"brief_{i:06d}")
        by_split[split].append(row)
        (metadata_out / f"brief_{i:06d}.json").write_text(
            json.dumps(
                {
                    "sample_id": f"brief_{i:06d}",
                    "profiles": profile_mix,
                    "images": copied_rel_images,
                    "findings": findings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    for name in ("train", "validation", "test"):
        write_jsonl(data_out / f"{name}.jsonl", by_split.get(name, []))
    (out_dir / "README.md").write_text(
        "# Brief Composer SFT Dataset\n\nComposite multi-image analytical briefing rows built from profile dataset outputs.\n",
        encoding="utf-8",
    )
    print(
        f"Built BriefComposer rows(train={len(by_split['train'])}, "
        f"val={len(by_split['validation'])}, test={len(by_split['test'])})"
    )
    if not args.no_upload:
        upload_dataset_folder(
            out_dir,
            args.upload_repo,
            private=args.private_repo,
            token=args.hf_token,
        )
        print(f"Uploaded to https://huggingface.co/datasets/{args.upload_repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

