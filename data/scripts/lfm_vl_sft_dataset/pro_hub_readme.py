"""Hugging Face dataset card README bodies for PRO mini-app SFT builders."""

from __future__ import annotations


def _dataset_yaml_frontmatter(*, tags: tuple[str, ...]) -> str:
    """
    Minimal YAML header so Hugging Face Hub README validation does not warn about
    missing dataset card metadata (see huggingface_hub README validation).
    """
    tag_lines = "\n".join(f"  - {tag}" for tag in tags)
    return f"""---
license: apache-2.0
language:
  - en
tags:
{tag_lines}
---

"""


def _split_table(*, n_train: int, n_val: int, n_test: int, n_tiles: int | None) -> str:
    lines = [
        "## Record counts (this build)",
        "",
        "| Split | JSONL lines |",
        "|-------|-------------|",
        f"| train | {n_train} |",
        f"| validation | {n_val} |",
        f"| test | {n_test} |",
        f"| **total** | **{n_train + n_val + n_test}** |",
        "",
    ]
    if n_tiles is not None:
        lines.extend(
            [
                f"Tiles processed (caption rows ≈ this; grounding rows added when regions exist): **{n_tiles}**.",
                "",
            ]
        )
    return "\n".join(lines)


def _common_tail(
    *,
    hub_repo_id: str,
    builder_script: str,
    orchestrator_hint: str,
    split_paragraph: str | None = None,
) -> str:
    split_block = split_paragraph or (
        "Train / validation / test are assigned from a **stable hash of `event_id`** "
        "(same `event_id` always lands in the same split)."
    )
    return f"""## Dataset layout

- `data/train.jsonl`, `data/validation.jsonl`, `data/test.jsonl` — VLM SFT samples (`messages` list with system/user/assistant content; images referenced by relative paths under this folder).
- `images/` — PNG chips (typically {orchestrator_hint}) consumed by the JSONL.
- `metadata/` — one JSON sidecar per tile/sample (scene ids, bbox, optional `regions`, profile tag).

## Splits

{split_block}

## Regenerating locally

Run from the **nutonic** repository root (paths relative to that root):

```bash
python data/scripts/{builder_script} <see --help for required args>
```

Upload to the Hub (requires a token with **write** access to the target dataset repo):

```bash
export HF_TOKEN="hf_..."   # or HUGGING_FACE_HUB_TOKEN
python data/scripts/{builder_script} ... --upload-repo {hub_repo_id} --hf-token "$HF_TOKEN"
```

Skip upload with `--no-upload`. Resume partial STAC downloads with `--skip-existing`.

### Orchestrator (all PRO profiles)

```bash
python data/scripts/run_pro_sft_orchestrator.py \\
  --events-per-profile 0 \\
  --hf-org YOUR_ORG \\
  --upload-repo-firewatch YOUR_ORG/firewatch-sft-v1 \\
  --hf-token "$HF_TOKEN"
```

Use `--upload-repo-<profile>` per profile, or `--hf-org` to upload to `YOUR_ORG/<default-repo-suffix>` for each builder. See `run_pro_sft_orchestrator.py --help`.

## Environment

| Variable | Purpose |
|----------|---------|
| `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` | Hub upload if `--hf-token` is not passed. |
| `HTTP_PROXY` / `HTTPS_PROXY` | Optional; if your network requires a proxy to reach STAC and Hugging Face. |

**STAC:** scenes are resolved from **Element84 Earth Search** (`sentinel-2-l2a` by default). No Earth Engine or Mapbox keys are required for this pipeline.

## Hub target for this artifact

**Dataset repo id:** `{hub_repo_id}`

Card URL: https://huggingface.co/datasets/{hub_repo_id}

## Limitations

- **Optical-only** Sentinel-2; cloud cover and revisit gaps can drop events or leave empty change masks.
- Detections and captions are **heuristic** (indices / thresholds), not operational truth labels.
- Assistant text follows conservative wording (candidates, confidence qualifiers).

"""


def firewatch_readme(
    *,
    hub_repo_id: str,
    n_train: int,
    n_val: int,
    n_test: int,
    n_tiles: int,
) -> str:
    body = f"""# FireWatch SFT

Temporal **Sentinel-2** image **pairs** (pre/post around a wildfire-relevant `event_date`) over a fixed AOI. **dNBR**-style burn signal drives a change mask; each tile emits a **change caption** row and, when regions exist, a **grounding** row with normalized bounding boxes.

{_split_table(n_train=n_train, n_val=n_val, n_test=n_test, n_tiles=n_tiles)}

## Inputs

- **Events:** JSON or CSV with `event_id`, `lat`, `lon`, `event_date` (see `data/events/fire_smoke_events.json` in the nutonic repo for examples).
- **CLI:** `build_lfm_vl_firewatch_sft.py --events … --max-events 0` processes every event row; tune `--bbox-half-km`, `--native-tile`, `--stride`, `--max-cloud-pct`, `--pre-window-days`, `--post-window-days`.

{_common_tail(hub_repo_id=hub_repo_id, builder_script="build_lfm_vl_firewatch_sft.py", orchestrator_hint="pre/post pair (`*_t0.png`, `*_t1.png`)")}
"""
    return _dataset_yaml_frontmatter(
        tags=("remote-sensing", "wildfire", "sentinel-2", "change-detection", "vlm-sft"),
    ) + body


def floodpulse_readme(
    *,
    hub_repo_id: str,
    n_train: int,
    n_val: int,
    n_test: int,
    n_tiles: int,
) -> str:
    body = f"""# FloodPulse SFT

Temporal **Sentinel-2** **pairs** for flood-relevant events. **MNDWI** water masks on pre/post scenes define **new inundation** (water gained); tiles get a **caption** and optional **grounding** rows for inundation regions.

{_split_table(n_train=n_train, n_val=n_val, n_test=n_test, n_tiles=n_tiles)}

## Inputs

- **Events:** JSON/CSV with `event_id`, `lat`, `lon`, `event_date` (example fixture: `data/events/flood_smoke_events.json`).
- **CLI:** `build_lfm_vl_floodpulse_sft.py --events … --max-events 0` for a full catalog pass.

{_common_tail(hub_repo_id=hub_repo_id, builder_script="build_lfm_vl_floodpulse_sft.py", orchestrator_hint="pre/post pair")}
"""
    return _dataset_yaml_frontmatter(
        tags=("remote-sensing", "flood", "sentinel-2", "change-detection", "vlm-sft"),
    ) + body


def landshift_readme(
    *,
    hub_repo_id: str,
    n_train: int,
    n_val: int,
    n_test: int,
    n_tiles: int,
) -> str:
    body = f"""# LandShift SFT

Temporal **Sentinel-2** **pairs** (longer baseline by default) over sampled locations. **NDVI delta** highlights land-cover–style change; tiles emit **change captions** and optional **grounding** for connected change regions.

{_split_table(n_train=n_train, n_val=n_val, n_test=n_test, n_tiles=n_tiles)}

## Inputs

- **Events file:** optional `--events` JSON/CSV (same schema as other PRO builders). If omitted, the builder uses **seeded global land-change hubs** (`sample_land_change_locations`).
- **CLI:** `build_lfm_vl_landshift_sft.py` — use `--max-events 0` with `--events` to consume the full file, or tune `--seeded-events` for synthetic hubs.

{_common_tail(hub_repo_id=hub_repo_id, builder_script="build_lfm_vl_landshift_sft.py", orchestrator_hint="pre/post pair")}
"""
    return _dataset_yaml_frontmatter(
        tags=("remote-sensing", "land-cover", "sentinel-2", "change-detection", "vlm-sft"),
    ) + body


def oceanscout_readme(
    *,
    hub_repo_id: str,
    n_train: int,
    n_val: int,
    n_test: int,
    n_tiles: int,
) -> str:
    body = f"""# OceanScout SFT

**Maritime** SFT samples from **Sentinel-2**. The pipeline **searches a temporal STAC pair** (for robust scene choice / metadata) but each training row uses a **single post-scene RGB chip** per tile. **NDWI** defines water; bright targets on water suggest **vessel candidates**. Each tile has a **maritime caption** row and, when detections exist, a **grounding** row.

{_split_table(n_train=n_train, n_val=n_val, n_test=n_test, n_tiles=n_tiles)}

## Inputs

- **Events:** optional `--events` JSON/CSV (`lat`, `lon`, `event_date`, …). If omitted, **seeded coastal hubs** (`sample_coastal_locations`) are used.
- **CLI:** `build_lfm_vl_oceanscout_sft.py` — default `--stride` is often **256** (fewer tiles than fire/flood). `--max-events 0` uses all seeded or file-loaded events.

{_common_tail(hub_repo_id=hub_repo_id, builder_script="build_lfm_vl_oceanscout_sft.py", orchestrator_hint="single `*_t1.png` path in JSONL (post scene)")}
"""
    return _dataset_yaml_frontmatter(
        tags=("remote-sensing", "maritime", "sentinel-2", "object-detection", "vlm-sft"),
    ) + body


def brief_composer_readme(
    *,
    hub_repo_id: str,
    n_train: int,
    n_val: int,
    n_test: int,
) -> str:
    body = f"""# BriefComposer SFT

**Multi-image** analytical **brief** rows composed from **completed** FireWatch, OceanScout, LandShift, and FloodPulse dataset folders (`metadata/` + `images/`). Each sample stitches 1–4 images and metadata-derived headlines into one **executive-style** assistant reply.

{_split_table(n_train=n_train, n_val=n_val, n_test=n_test, n_tiles=None)}

## Inputs

- **Source roots:** one or more `--source-root` directories (each must contain `images/` and `metadata/` from the profile builders).
- **CLI:** `build_lfm_vl_brief_sft.py --samples N` controls JSONL line count. Run **after** the four temporal profile datasets are built so metadata and PNGs exist.

{_common_tail(
        hub_repo_id=hub_repo_id,
        builder_script="build_lfm_vl_brief_sft.py",
        orchestrator_hint="mixed profile images per row",
        split_paragraph=(
            "Train / validation / test use a **stable hash** of the synthetic sample id "
            "(`brief_######`) assigned at compose time."
        ),
    )}
"""
    return _dataset_yaml_frontmatter(
        tags=("remote-sensing", "multi-image", "reasoning", "vlm-sft"),
    ) + body
