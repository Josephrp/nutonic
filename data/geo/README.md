# `data/geo/` — offline geographic baselines

This directory holds **Natural Earth** 1:50m vector extracts (and optionally **GeoNames** `countryInfo.txt`) used by `data/scripts/build_poi_geo_context.py` and the shipped-cache hint pipeline. **Default layout is gitignored** except this README; run the fetch script once per machine or CI cache.

## License

- **Natural Earth:** [Public Domain](https://www.naturalearthdata.com/about/terms-of-use/).
- **GeoNames** (optional): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — keep `geonames/NOTICE.txt` next to any `countryInfo.txt` you redistribute.

## How to fetch

From the **repository root**:

```bash
pip install -r data/scripts/requirements.txt
python data/scripts/fetch_geo_baselines.py --output-dir data/geo
```

Optional GeoNames country metadata:

```bash
python data/scripts/fetch_geo_baselines.py --output-dir data/geo --fetch-geonames
```

- **`MANIFEST.json`** — records SHA256 of each downloaded zip for idempotent re-runs.
- **`--dry-run`** — print the plan without writing files.
- **`--force`** — re-download and re-extract even when hashes match the manifest.

## Layout (after fetch)

| Path | Content |
|------|---------|
| `zips/*.zip` | Cached Natural Earth archives |
| `natural_earth/50m/<artifact_id>/` | Unpacked shapefiles per layer |
| `geonames/countryInfo.txt` | Optional GeoNames extract |
| `geonames/NOTICE.txt` | Attribution (written when GeoNames is enabled) |
| `MANIFEST.json` | Pin file for CI / idempotency |

## CI

Automated tests **do not** download full Natural Earth. Use **mocked HTTP** in `data/scripts/tests/test_fetch_geo_baselines.py`, or cache `data/geo/` in a workflow artifact. For **`build_poi_geo_context`**, set **`NE_FIXTURE_ROOT`** to a clipped fixture tree (see `plans/2026-04-14-data-scripts-testing-and-ci.md`).
