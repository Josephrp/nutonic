"""
Normalize VLM SFT Parquet rows to a single schema compatible with
``NuTonic/sat-vl-sft-training-ready-v1``-style shards.

Some hubs (e.g. ``NuTonic/firewatch-sft-v1``) use legacy column names
(``metadata.event_id``, ``metadata.profile``) and extra columns (``regions``).
Ray / Arrow multi-file reads expect a consistent schema across shards.
"""

from __future__ import annotations

import json
from typing import Any


def _rel_image_paths_from_messages(messages: Any) -> list[str]:
    out: list[str] = []
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except json.JSONDecodeError:
            return out
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image":
                continue
            image = part.get("image")
            if not isinstance(image, str):
                continue
            if image.startswith(("http://", "https://", "/")):
                continue
            out.append(image)
    return out


def normalize_vlm_sft_parquet_row(
    row: dict[str, Any],
    *,
    default_task: str | None = None,
    default_split: str = "train",
) -> dict[str, Any]:
    """
    Return a row with only ``messages``, ``metadata``, ``_postprocess`` in the
    canonical training-ready shape. Drops ``regions`` and other extras.
    """
    raw_meta = row.get("metadata")
    if not isinstance(raw_meta, dict):
        raw_meta = {}

    sample_id = raw_meta.get("sample_id") or raw_meta.get("event_id") or ""
    sample_id = str(sample_id).strip() if sample_id is not None else ""

    task_raw = raw_meta.get("task")
    if task_raw is None or (isinstance(task_raw, str) and not str(task_raw).strip()):
        task = (default_task or "sft").strip()
    else:
        task = str(task_raw).strip()

    analysis_profile = raw_meta.get("analysis_profile") or raw_meta.get("profile") or ""
    analysis_profile = str(analysis_profile).strip() if analysis_profile is not None else ""

    tile_stem = raw_meta.get("tile_stem") or ""
    tile_stem = str(tile_stem).strip() if tile_stem is not None else ""

    split_raw = raw_meta.get("split")
    if split_raw is None or (isinstance(split_raw, str) and not str(split_raw).strip()):
        split = default_split
    else:
        split = str(split_raw).strip()

    image_paths = raw_meta.get("image_paths")
    if not isinstance(image_paths, list):
        image_paths = []
    image_paths = [str(x) for x in image_paths]

    aip = raw_meta.get("analysis_image_path")
    analysis_image_path = str(aip).strip() if aip else ""

    messages = row.get("messages")
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except json.JSONDecodeError:
            messages = []
    if not isinstance(messages, list):
        messages = []

    if not image_paths:
        image_paths = _rel_image_paths_from_messages(messages)

    pp = row.get("_postprocess")
    if not isinstance(pp, dict):
        pp = {}
    minify = pp.get("minify_tim_json")
    if not isinstance(minify, bool):
        minify = True
    final_pass = pp.get("final_training_pass")
    if not isinstance(final_pass, bool):
        final_pass = True

    return {
        "messages": messages,
        "metadata": {
            "sample_id": sample_id,
            "task": task,
            "analysis_profile": analysis_profile,
            "tile_stem": tile_stem,
            "split": split,
            "image_paths": image_paths,
            "analysis_image_path": analysis_image_path,
        },
        "_postprocess": {
            "minify_tim_json": minify,
            "final_training_pass": final_pass,
        },
    }
