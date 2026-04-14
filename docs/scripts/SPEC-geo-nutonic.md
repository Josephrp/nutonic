# Module specification: `geo_nutonic.py`

**Path:** `data/scripts/geo_nutonic.py` (**planned** extraction from `download_geoguessr_poi_imagery.py`)  
**Status:** Not yet implemented; **normative** API for all pipeline scripts that need shared geodesy.

---

## 1. Purpose

Single **lightweight** module (stdlib + **NumPy** optional; **no PyTorch**, no `refs/` imports) providing:

- **`haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float`** — great-circle km, **(lon, lat)** order, consistent with **`refs/terramind-geogen-main/src/geo_utils.py`** semantics (see [SPEC-download-geoguessr-poi-imagery.md](SPEC-download-geoguessr-poi-imagery.md) §3).
- **`clamp_distance_km(d: float, max_km: float | None) -> float`** — utility for bucketing.
- **`bearing_deg(lon1, lat1, lon2, lat2) -> float`** (optional) — for Mapbox bearing if needed.

---

## 2. Test requirement

- **Unit tests** in `data/scripts/tests/test_geo_nutonic.py` (or `server/tests` if shared) comparing a small table of points against a **reference** implementation (hand-calculated or `pyproj` Geod) with tolerance **< 0.01 km** for 10k km scale.

---

## 3. Forbidden dependencies

- **`torch`**, **`terratorch`**, **`transformers`** — forbidden.
- **`geopandas`** — **not** in this module; use in **`build_poi_geo_context`** only.

---

## 4. Migration plan

1. Copy `haversine_km` from `download_geoguessr_poi_imagery.py` unchanged.
2. Switch downloader + **`build_poi_geo_context`** + **`compile_useful_hint_tiers`** to `from geo_nutonic import haversine_km`.
3. Delete duplicate definitions.

---

*Spec version: 2026-04-14*
