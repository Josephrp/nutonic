# NU:TONIC — Data scripts: testing strategy and CI

**Date:** 2026-04-14  
**Parent:** [`plans/2026-04-14-data-scripts-implementation-track.md`](2026-04-14-data-scripts-implementation-track.md)  
**Specs:** [`docs/scripts/README.md`](../docs/scripts/README.md)

---

## 1. Test layout

```text
tools/tests/
  test_batch_streetview_hints.py
data/scripts/tests/
  conftest.py                 # REPO_ROOT, fixture paths
  test_geo_nutonic.py
  test_validate_hint_strings.py
  test_catalog_import_poi.py
  test_catalog_lint.py
  test_render_mapbox_still.py
  test_build_poi_geo_context.py
  test_compile_useful_hint_tiers.py
  test_assemble_manifest.py
  test_assemble_ranked_clue_pack.py
  test_generate_ai_guess_fixture.py
  test_validate_caption_text.py
  fixtures/
    poi_mini/                 # 2 POIs, layout A + B
    geo/                      # clipped NE-compatible GeoJSON or small GPKG
    hints_valid.json
    hints_bad_coords.json
    maps/reuse_stub.png           # tiny PNG for render_mapbox_still reuse-only tests
    catalog_ok/
    catalog_broken/
```

---

## 2. Fixture policy

| Concern | Approach |
|---------|----------|
| **Natural Earth full size** | Not in git; CI sets **`NE_FIXTURE_ROOT`** to `tests/fixtures/geo` containing **clipped** layers (single country bbox). |
| **Mapbox** | No network in default CI: **`--reuse-only`** + 1×1 PNG or small real PNG committed (< 20 KB). |
| **HF datasets** | Downloader tests **mock** `datasets.load_dataset` or mark **`@pytest.mark.integration`** skipped. |
| **Street View batch** | Default **on** in CI via **`httpx.MockTransport`** (`tools/tests/test_batch_streetview_hints.py`). Optional **`RUN_STREETVIEW_BATCH=1`** for live pano + GPU LFM against real service URLs. |

---

## 3. Determinism

- **`random_seeded`** mode tests fix `--seed`.
- **`assemble_manifest`** snapshot tests normalize line endings (`\n`) and sort keys.

---

## 4. CI job wiring

**Implemented** in **`.github/workflows/nutonic-ci.yml`** (`data-scripts-unit-tests` job):

```yaml
pip install -r data/scripts/requirements.txt -r tools/requirements.txt pytest \
  ./inference/streetview_pano_service ./inference/lfm_vl_hint_service
python -m pytest data/scripts/tests tools/tests \
  inference/streetview_pano_service/tests inference/lfm_vl_hint_service/tests -q
```

Path filters include **`tools/**`** and **`inference/streetview_pano_service/**`**, **`inference/lfm_vl_hint_service/**`**.

**Markers:** `@pytest.mark.integration` for slow/network tests (optional for future live Street View runs).

---

## 5. Local developer loop

```text
pip install -r data/scripts/requirements.txt
export NE_FIXTURE_ROOT=data/scripts/tests/fixtures/geo
python data/scripts/fetch_geo_baselines.py --output-dir data/geo    # once, optional
python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12
python data/scripts/catalog_lint.py
pip install -r tools/requirements.txt
pip install ./inference/streetview_pano_service ./inference/lfm_vl_hint_service
pytest data/scripts/tests tools/tests inference/streetview_pano_service/tests inference/lfm_vl_hint_service/tests -q
```

---

## 6. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-14 | Initial testing + CI supplement |
| 0.2 | 2026-04-14 | Street View batch: **`tools/tests`**, inference stub tests, **`validate_caption_text`**, CI install line |

---

*End of document.*
