---
title: NU:TONIC PRO materialization
emoji: 🗺️
colorFrom: yellow
colorTo: orange
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — PRO materialization service

Published from `inference/pro_materialization_service` (CPU / IO — **no** `torch` in `pyproject` core deps).

## Hardware

**CPU** Space is expected (Mapbox fetch, optional Sentinel / STAC when extras installed).

## Environment variables

| Name | Description |
|------|-------------|
| `MAPBOX_ACCESS_TOKEN` | Required for Mapbox static / tile fetches (secret) |
| `NUTONIC_INBOUND_HMAC_SECRET` | When game server signs requests to this worker |
| Additional STAC / AWS keys | If you enable Sentinel paths — see package README |
