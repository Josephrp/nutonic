# Maps and gameplay patterns

## Rule: abstract the map behind a single interface

Define in **`commonMain`** something like `MapViewport` / `GameMapController` with:

- Camera position / zoom bounds suitable for guessing
- **Tap-to-place** guess marker with **enlarged hit target** (invisible padding per spec footgun)
- Optional overlays: grid, scan distortion, timer HUD, peer “ghost” markers (when multiplayer requires)

**Do not** embed Google Maps, MapKit, OSM, or WebGL calls directly inside random composables.

## Parity rule

Each platform provides an **actual** implementation of the map port that satisfies the same interface. Visual skin (tiles vs stylized map) may differ slightly, but **gestures, guess submission, and feedback timing** must align.

## Feedback timing

- UI must respond to tap/place within **~100ms** perceived latency (spec footgun): optimistic local marker + server reconciliation pattern is acceptable.

## Imagery and keys

- Satellite or styled tiles: **keys and EULAs** are platform- and provider-specific; centralize configuration (build config, plist, env) **outside** composables.

## Desktop and web

- If the reference desktop module uses OSM, that is one **valid** engine; iOS/Android may use native SDKs. Document which engine each target uses in one place (e.g. `mapview-desktop/README` successor section).

## Game loop (client responsibilities)

1. Load round / clue state from server (or mock).
2. User places guess on map → send coordinates + metadata to server.
3. Show **success overlay** with server-returned distance/score/XP (client may show provisional animation but **authoritative numbers** come from server).
4. Navigate to **full results**; leaderboard section **hydrates** from API (see networking rules).

For the **VLM + Street View clues, progressive server-driven zoom per turn, glass chat overlay, join-in-progress matches, and post-human AI marker** loop—and how **`refs/terramind-geogen-main`** (TerraMesh, haversine, heatmaps) informs server-side scoring and difficulty—see **`10-terramesh-vlm-progressive-zoom-game-engine.md`**.
