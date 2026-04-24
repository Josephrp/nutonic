# OceanScout PRO Contract

OceanScout is the maritime PRO mini-app for ship detection and maritime activity intelligence. It reports evidence-backed presence indicators, not legal findings or enforcement conclusions.

## Output Contract

OceanScout jobs use `analysis_profile = "oceanscout_ship_detection"` and return PRO artifacts through the merged job artifact surfaces: `ProJobStatusOut.artifacts`, `analysis_artifacts`, `brief_artifacts`, and `on_device_payload.overlay_refs`.

Current baseline analytics may also expose `materialization_summary.profile_analytics` fields such as `observation_coverage`, `detection_score_summary`, `confidence`, `evidence_level`, `limitations`, and `shoreline_policy`. These are evidence summaries derived from available TiM/materialization samples; they are not a substitute for domain-reviewed vessel detection until the required artifacts below are emitted.

Required artifact kinds:

- `vessel_candidates`: JSON list of scored candidate detections with `candidate_id`, `center_lat`, `center_lon`, `confidence`, `evidence_level`, `timestamp`, and `source_layers`. Empty lists mean "no candidates emitted by this run", not "no vessels exist".
- `lane_heatmap`: GeoJSON or raster heatmap normalized by valid observation coverage, not raw detection count.
- `incursion_events`: JSON or GeoJSON list of geofence presence indicators. Copy must use "possible presence" or "candidate incursion", never "illegal activity detected".
- `observation_coverage`: JSON coverage denominator by time slice, including cloud, glint, no-observation, and valid-observation counts.
- `evidence_level`: Summary JSON that labels evidence as `optical_only` or `tim_pseudosar_plus_lulc` and includes limitations.

## Claim Safety

OceanScout outputs must include:

- `confidence`: calibrated score or bin for every candidate and aggregate panel.
- `notices`: plain-language caveats for cloud, sun glint, shoreline ambiguity, and pseudo-SAR limitations.
- `limitations`: machine-readable list consumed by UI and Brief Composer.
- `observation_coverage`: displayed before any claim-oriented summary so users see the denominator for the analysis.

Approved language: "candidate vessel", "possible vessel presence", "observation-limited", "requires corroboration".

Disallowed language without external corroboration: "illegal fishing", "smuggling", "confirmed incursion", "SAR-confirmed".

## Demo Overlay Semantics

When comparing base-model and TiM-enhanced outputs in demo mode:

- Green overlays represent base optical detections.
- Blue overlays represent TiM-enhanced candidate detections.
- Heatmaps are normalized by `observation_coverage.valid_observation_count`.
- No-observation cells must render as "insufficient observation", not zero activity.

## Validation Scenarios

- New York Harbor: near-shore and harbor candidates must survive the shoreline buffer policy.
- Channel Islands: geofence panels must describe candidates as presence indicators and include observation coverage.
- Cloud/glint stress: no-observation conditions must produce warnings instead of false zero-detection summaries.
