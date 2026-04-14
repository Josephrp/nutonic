# NU:TONIC — Data scripts: testing strategy and CI

**Date:** 2026-04-14  
**Parent:** [`plans/2026-04-14-data-scripts-implementation-track.md`](2026-04-14-data-scripts-implementation-track.md)  
**Specs:** [`docs/scripts/README.md`](../docs/scripts/README.md)

---

## 1. Test layout

```text
data/scripts/tests/
  conftest.py                 # REPO_ROOT, fixture paths
  test_geo_nutonic.py
  test_validate_hint_strings.py
  test_catalog_import_poi.py
  test_catalog_lint.py
  test_build_poi_geo_context.py
  test_compile_useful_hint_tiers.py
  test_assemble_manifest.py
  test_assemble_ranked_clue_pack.py
  fixtures/
    poi_mini/                 # 2 POIs, layout A + B
    geo/                      # clipped NE-compatible GeoJSON or small GPKG
    hints_valid.json
    hints_bad_coords.json
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
| **Street View batch** | Default skip; nightly sets **`RUN_STREETVIEW_BATCH=1`** + service URLs. |

---

## 3. Determinism

- **`random_seeded`** mode tests fix `--seed`.
- **`assemble_manifest`** snapshot tests normalize line endings (`\n`) and sort keys.

---

## 4. CI job wiring

Add to **`.github/workflows/nutonic-ci.yml`** (or new `data-scripts-ci.yml`):

```yaml
# Illustrative — adapt to repo workflow style
data-scripts-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install -r data/scripts/requirements.txt
    - run: pip install pytest
    - run: pytest data/scripts/tests -q -m "not integration"
```

**Markers:** `@pytest.mark.integration` for slow/network tests.

---

## 5. Local developer loop

```text
pip install -r data/scripts/requirements.txt
export NE_FIXTURE_ROOT=data/scripts/tests/fixtures/geo
python data/scripts/fetch_geo_baselines.py --output-dir data/geo    # once, optional
python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12
python data/scripts/catalog_lint.py
pytest data/scripts/tests -q
```

---

## 6. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-14 | Initial testing + CI supplement |

---

*End of document.*
