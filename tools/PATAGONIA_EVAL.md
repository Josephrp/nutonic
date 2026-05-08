# Patagonia VLM + TiM evaluation

This folder contains the **Patagonia** multimodal harness: reference stills (STAC Sentinel-2 or Mapbox), optional **STAC gold refresh** (COG RGB + SCL aligned chips, `gold/<target_id>.json` sidecars), local **TerraMind TiM** export, SFT-style **production_analysis** prompts, and scoring (lexical, grounding, output contract, faithfulness, composite).

## Entry points

| Script | Role |
|--------|------|
| `evaluate_vlm_patagonia.py` | Baseline Patagonia VLM eval (stills + endpoints + lexical-style scoring). |
| `evaluate_vlm_patagonia_tim_e2e.py` | Full TiM-in-prompt E2E: TiM batch, analytics injection, multimodal scores, optional counterfactuals, HF upload. |

## Dynamic World (optional)

When `--still-source stac` and STAC gold refresh runs, you can add:

```text
--fetch-dynamic-world
```

That calls Google Earth Engine (`GOOGLE/DYNAMICWORLD/V1`) for a **label** chip on the **same Web Mercator grid** as the eval RGB/SCL chip (see `patagonia_eval_dynamic_world.py` and `data/scripts/lfm_vl_sft_dataset/ee_dynamic_world.py`). Results are stored on the gold sidecar as:

- `dynamic_world_fractions` — class-id → fraction (same convention as procedural LULC inputs)
- `dynamic_world_fetch` — diagnostics (`ok`, `reason`, EE tries, etc.)

**Auth (pick one):**

1. **Headless / CI (recommended):** service account JSON + Earth Engine access — set `GOOGLE_APPLICATION_CREDENTIALS` (or `EE_SERVICE_ACCOUNT_KEY_PATH`) and a project id (`EE_PROJECT`, `GOOGLE_CLOUD_PROJECT`, `EE_PROJECT_ID`, …). The harness calls `lfm_vl_sft_dataset.ee_auth.initialize_earth_engine`, same as SFT dataset tooling.
2. **Interactive:** `earthengine authenticate`, then ensure a project id is set if required.

**Skip EE entirely:** `NUTONIC_SKIP_EE_DYNAMIC_WORLD=1` — no Dynamic World chip; sidecars record `dynamic_world_fetch.reason=skipped_env` (no repeated login errors). Failed login is **cached per process** after the first attempt so each target does not re-log the same `EEException`.

**Remote host after `scp` of a service-account JSON:** the EE client does **not** auto-read `~/.config/gcloud/`; you must export:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/radioshaq-ee.json
# Optional if JSON contains project_id (tools now infer it): 
# export GOOGLE_CLOUD_PROJECT=radioshaq
chmod 600 "$GOOGLE_APPLICATION_CREDENTIALS"
```

The service account **email** must be allowed to use Earth Engine (Register a service account in the EE Cloud Console / legacy EE signup flow). Without that step, auth succeeds against Google but EE API calls can still fail.

**Marine SCL prior:** if strict SCL→DW fractions are empty (e.g. heavy cloud) but `category` is a marine MPA class, the gold sidecar may set `sentinel_scl_fractions` to 100% DW water (`sentinel_scl_fractions_tag: marine_water_prior`) so `procedural_or_dw` does not return `no_inputs`.

**Analytics:** use `--analytics-source dynamic_world` to require DW fractions when present (falls back to SCL-derived procedural fractions with resolved source `dynamic_world_fallback_scl`). Use `--analytics-source procedural_or_dw` to prefer healthy **TiM** JSON, else DW fractions, else SCL procedural.

## Analytics sources (summary)

- `none` — image-only user prompt (no TiM JSON block).
- `procedural` — SFT-aligned JSON from **SCL** chip fractions.
- `dynamic_world` — procedural-shaped JSON from **Dynamic World** fractions when the sidecar has them.
- `procedural_or_dw` — TiM if healthy, else DW fractions, else SCL.
- `procedural_or_tim` — TiM if healthy, else SCL procedural.
- `tim_generated` — always use local TiM compact JSON (subject to health in reporting).
- `synthetic_oracle` — curated fractions from `tools/data/patagonia_synthetic_oracle.yaml`.

## Report payload extras

`report.json` includes `summary_by_model`, `summary_by_model_by_category`, and **`summary_by_model_by_profile`** (aggregate stats keyed by effective `analysis_profile` on each row).

## Eval targets

Curated AOIs live in `default_patagonia_targets()` in `evaluate_vlm_patagonia.py`. Some rows set `analysis_profile_hint` (e.g. `wildfire`, `flood_pulse`) so TiM and procedural analytics use the matching SFT profile.

### Temporal scenes

`EvalTarget.temporal_scenes` is a tuple of STAC `datetime` intervals (e.g. `("2024-11-01/2025-01-31", "2025-11-01/2026-01-31")`). When set, the harness resolves a per-target effective interval and applies it to:

- the STAC reference still fetch (`write_patagonia_eval_still`)
- the STAC gold refresh (`_refresh_stills_with_stac_cog_gold`)
- the Dynamic World fetch fallback (`_attach_dynamic_world_to_sidecar`)
- each TiM batch row (`_tim_batch_row_for_target`)

Resolution mode is controlled by `--temporal-scenes-mode`:

- `latest` (default) — use the **last** entry as the per-target `datetime`. STAC implicitly picks a recent scene; if your profile uses bi-temporal slices (e.g. `wildfire`, `flood_pulse`), TiM auto-derives `t0`/`t1` from this window.
- `union` — combine the earliest start with the latest end into a wide search interval.

Per-target temporal context is stored in `gold/<target_id>.json` (`temporal_scenes`, `temporal_scenes_mode`, `temporal_datetime_effective`) and in `report.json[meta].temporal_scenes_by_target`.

### Synthetic oracle

`tools/data/patagonia_synthetic_oracle.yaml` contains curated Dynamic World class fractions per AOI (one entry per default target). It feeds `--analytics-source synthetic_oracle` for faithfulness upper-bound experiments. Numbers are best-effort priors per AOI; adjust as new scenes/seasons are evaluated.
