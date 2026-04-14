# Script specification: `batch_streetview_hints.py`

**Path:** `tools/batch_streetview_hints.py`  
**Status:** **Implemented** (**Phase D**) — **`inference/streetview_pano_service`** (`POST /v1/panos/sample`, synthetic JPEG frames) + **`inference/lfm_vl_hint_service`** (`POST /v1/suggestions/from_frames`, optional `POST /v1/narrative/fuse`). LFM backend: **`LFM_VL_BACKEND=stub`** (CI default), **`transformers`** (official **Liquid** HF `AutoModelForImageTextToText`, see [Liquid LFM2.5-VL-450M](https://docs.liquid.ai/lfm/models/lfm25-vl-450m)), or **`openai_compatible`** (vLLM/SGLang OpenAI `/v1/chat/completions`).  
**Plan:** [`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`](../../plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md), [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §5.0.

---

## 1. Purpose

Offline batch driver with a **fixed multi-stage pipeline** (see §1.1). In short: **select a configurable set of POIs** → for each POI, **capture a configurable number of Street View screenshots** (static / pano-derived frames per sampling policy) → send those images to **LFM-VL** for **per-batch or per-viewpoint captioning** → optionally run a **final text-only LFM (LLM) pass** to fuse captions into a short **narrative** string for chrome / INTEL-style copy (still validated; **no** second vision forward required).

Internal HTTP services (URLs are **contracts**; backends are swappable):

1. **`inference/streetview_pano_service`** — returns **`frames[]`** (image bytes + `pano_id`, headings, attribution); frame count is **operator-configurable** and must match what LFM-VL expects (bounded `max_suggestions` / token budget).
2. **VLM captioning** — **`POST /v1/suggestions/from_frames`** (or adapter-mapped equivalent): all screenshots for that POI in **one** request (or chunked batches if **`--lfm-max-frames-per-request`** is exceeded — merge `suggestions[]` deterministically by `viewpoint_id` order). The process behind **`--lfm-vl-url`** may be **`lfm_vl_hint_service`** (**`transformers` + PyTorch**), a **vLLM** deployment exposing an OpenAI-compatible chat/completions API with a thin shim, or another approved worker — see `inference/README.md` §Runtime backends.

Primary ship field remains **`streetview_hint_pack`** (see **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`** §4).

**Optional satellite hop (unchanged):** when **`--satellite-caption-service-url`** is set and **`render_mapbox_still`** output exists for the row, call **`inference/lfm_vl_satellite_caption_service`** `POST /v1/infer` with **`task=caption`** on the **Mapbox still** bytes. Merge into a **separate** manifest-ready structure with **`pipeline: "satellite_lfm_vl_specialist"`** — **never** interleave unlabeled with `streetview_hint_pack` entries (`docs/GAME-ENGINE.md` §5.2).

---

## 1.1 Pipeline stages (normative)

| Stage | What runs | Configuration |
|-------|-------------|----------------|
| **S0 — POI selection** | Resolve **`location_id`** list from **`--catalog-root`** (and optional **`--poi-root`** join). | **`--poi-limit N`**: process at most **N** locations after stable sort (default **all** catalog rows, or **12** when using smoke root only). **`--location-ids poi_0001,poi_0002`** or **`--location-ids-file`** overrides subset. **`--shuffle-seed`** optional for reproducible subsampling when `N < total`. |
| **S1 — Street View screenshots** | **`streetview_pano_service`**: for each selected POI, request **`K`** frames (JPEG/PNG) per policy. | **`--sv-screenshots-per-location K`** (alias **`--frame-count`**): default **6** unless pano service contract changes; must align with `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §2.2 `count`. Additional knobs (radius, size) follow **`--pano-policy`** YAML or CLI mirrors documented in that plan. |
| **S2 — LFM-VL captioning** | **`lfm_vl_hint_service`**: **`frames[]` → `suggestions[]`**; map each suggestion line to **`streetview_hint_pack`** entries (`text`, `viewpoint_id`, `rank`). | **`--lfm-vl-url`**, **`--model-profile tiny`**, **`--prompt-template-version`**, **`--lfm-max-frames-per-request`** (split if `K` too large for VRAM). |
| **S3 — Optional LFM LLM narrative (text-only)** | **No images**: send **structured text** only — e.g. JSON list of `{ "viewpoint_id", "caption" }` from S2 + allowlisted **`mission_flavor` / `role_presentation`** — to a **text LFM** or **OpenAI-compatible** endpoint configured for short prose. | **`--enable-narrative-pass`**. **`--narrative-backend lfm_text|openai|ollama`** + **`--narrative-service-url`**. Output: single string **`streetview_assist_narrative`** (or merge into manifest narrative sidecar per product). **Must** pass **`validate_hint_strings`** caption rules (no coordinates). |

**Design intent:** S2 does **visual** captioning; S3 does **composition** only. S3 **must not** receive raw lat/lon or full-resolution EXIF; if the text backend cannot be trusted, skip S3 for ranked packs.

---

## 2. Non-goals

- Does **not** embed golden coordinates in responses stored for **ranked** client packs.
- Does **not** authenticate as a player; uses **operator** credentials (mTLS / `INFERENCE_HMAC_SECRET` per thin orchestrator plan).

---

## 3. Inputs

| Flag | Description |
|------|-------------|
| **`--poi-root`** | Default `data/downloads/geoguessr_poi_12` |
| **`--catalog-root`** | For `map_id` / `location_id` join |
| **`--pano-service-url`**, **`--lfm-vl-url`** | Base URLs for pano service and **LFM-VL hint** service (`--lfm-service-url` accepted as alias for **`--lfm-vl-url`**) |
| **`--poi-limit`** | Max number of catalog locations to process in this run (**S0**) |
| **`--location-ids`**, **`--location-ids-file`** | Explicit subset instead of full catalog |
| **`--sv-screenshots-per-location`** (**`--frame-count`**) | **K** Street View frames per POI (**S1**); default **6** |
| **`--lfm-max-frames-per-request`** | If **K** exceeds GPU policy, chunk frames across multiple LFM calls then merge captions in order |
| **`--satellite-caption-service-url`** | Optional base URL for **`lfm_vl_satellite_caption_service`** (Mapbox still → caption) |
| **`--still-index`** | Path to JSON index from **`render_mapbox_still`** (location_id → jpeg path or bundle id) |
| **`--model-profile tiny`** | Maps to smallest checkpoint + low `max_new_tokens` |
| **`--enable-narrative-pass`**, **`--narrative-backend`**, **`--narrative-service-url`** | Optional **S3** text-only narrative fuse (see §1.1) |
| **`--skip-streetview-hints`** | No-op success (for CI without GPU) |

---

## 3.1 Request payload to LFM hint service (normative sketch)

For each `location_id`, after pano fetch:

- **`frames[]`:** each element includes `image_base64` (or multipart equivalent), `pano_id`, `heading_deg`, optional `pitch_deg`.
- **`ranked_clue_safe`:** default **`true`** for shipped batches so templates follow strict no–place-name rules where product requires (`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §3.3).
- **`prompt_template_version`:** must match the deployed hint service.
- **Do not** pass raw golden lat/lon in the JSON body; pano service already used catalog truth for sampling **offline** — the LFM service **must not** echo coordinates in returned text (enforce via **`validate_hint_strings`** caption mode).

**Unobvious logic issue:** feeding **`useful_hints` tier strings** into the Street View LFM prompt can **anchor** the VLM to country/region names and **inflate confidence** on decoy panos. Default: **omit** text hints from the SV LFM request; optional **`--inject-useful-hint-tone`** (off by default) may pass **non-spoiler** mission flavor only.

---

## 4. Output

- **`data/cache/<version>/streetview/<location_id>.json`**:

```json
{
  "location_id": "poi_0067",
  "streetview_hint_pack": [
    { "text": "…", "viewpoint_id": "decoy-1", "rank": 1 }
  ],
  "streetview_assist_narrative": null,
  "model_pins": { }
}
```

- Each **`streetview_hint_pack[].text`** must pass **`validate_hint_strings`** in **caption mode** (no coords, max length).
- **`streetview_assist_narrative`:** when **`--enable-narrative-pass`** is set, a **single** fused prose string (INTEL / mission chrome); **null** otherwise. Same validator rules; **shorter** max length than sum of pack lines (policy YAML, e.g. ≤ 900 chars).

**`model_pins`:** merge per-run objects for **`streetview_pano_service`**, **`lfm_vl_hint_service`**, optional **`lfm_vl_satellite_caption_service`**, and optional **narrative text backend** (`model_id`, `revision`, `prompt_template_version` / `prompt_pack_version`) into the cache reports file referenced in **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`** §8.

---

## 5. Rate limits and retries

- Respect Google / Mapbox quotas; exponential backoff; per-POI **timeout** (e.g. 120s) with partial failure recorded in **`reports/streetview_failures.json`**.

---

## 6. CLI

```text
python tools/batch_streetview_hints.py
  --catalog-root data/catalog
  --poi-root data/downloads/geoguessr_poi_12
  --pano-service-url http://127.0.0.1:7861
  --lfm-vl-url http://127.0.0.1:7862
  [--poi-limit 12]
  [--sv-screenshots-per-location 6]
  [--lfm-max-frames-per-request 6]
  [--enable-narrative-pass --narrative-backend ollama --narrative-service-url http://127.0.0.1:11434]
  [--content-version 2026-04-14]
  [--skip-streetview-hints]
```

---

## 7. Exit codes

| Code | Meaning |
|------|---------|
| 0 | All POIs processed (partial failures OK if `--allow-partial`) |
| 9 | Hard failure (service unreachable, auth) |

---

## 8. Related

- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- [SPEC-validate-hint-strings.md](SPEC-validate-hint-strings.md)
- [SPEC-render-mapbox-still.md](SPEC-render-mapbox-still.md) — still bytes for optional satellite caption hop

---

*Spec version: 2026-04-14e — **Implemented** local runner (`tools/` + `inference/*` stubs); optional satellite / GPU backends unchanged*
