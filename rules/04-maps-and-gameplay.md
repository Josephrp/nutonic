# Maps and gameplay patterns

## Rule: abstract the map behind a single interface

Define in **`commonMain`** something like `MapViewport` / `GameMapController` with:

- **Basemap mode** — At minimum **`SATELLITE`**, **`ROADMAP`**, and **`HYBRID`** (or nearest equivalent per SDK); one shared enum + platform mapping document.
- **Reference clue layer** — **Mapbox Static Images** (or product-approved equivalent) as a **non-interactive** or lightly interactive **still** aligned to the round; keys and URL signing stay **outside** `commonMain`.
- **Guess modal** — **Expandable** UI **anchored bottom-right** of the reference image: **search** (geocoder/places), coordinate readout, **submit guess** (single primary submission per round per `docs/GAME-ENGINE.md`); collapsed state shows a **handle** so the map stays usable.
- **Optional assist panels** — **Collapsible** UI for **Street View description** text, **useful-hint tiers** (three pre-cached specificity levels), and **Reveal uplink** (peer marker hint); each independent of the reference still and narrative overlay (`docs/GAME-ENGINE.md` §9).
- Camera position / zoom bounds suitable for guessing (**authoritative on the client** for **non-ranked** missions; **ranked** missions may require **server-issued** viewport / zoom steps per `round_ticket`—apply server bounds without local invention of truth, `docs/RANKED-MODE.md`)
- **Tap-to-place** on the main map (optional if modal-only flow wins) with **enlarged hit target** (invisible padding per spec footgun)
- Optional overlays: grid, scan distortion, timer HUD; **narrative overlay modal** supports **authorial text** and **user text input**; **assist** text (Street View pack, useful hints) uses **separate collapsible** surfaces per `rules/06-server-vlm-tim-and-on-device-ml.md`

**Do not** embed Google Maps, MapKit, OSM, or WebGL calls directly inside random composables.

## Parity rule

Each platform provides an **actual** implementation of the map port that satisfies the same interface. Visual skin (tiles vs stylized map) may differ slightly, but **gestures, guess submission, and feedback timing** must align.

## Feedback timing

- UI must respond to tap/place within **~100ms** perceived latency (spec footgun): **local** marker immediately; optional **REST** follow-up (telemetry, ranked ticket checks, optional community rows) must **not** block the primary tap feedback (`docs/GAME-ENGINE.md` §14).

## Imagery and keys

- Satellite or styled tiles: **keys and EULAs** are platform- and provider-specific; centralize configuration (build config, plist, env) **outside** composables.

## Desktop and web

- If the reference desktop module uses OSM, that is one **valid** engine; iOS/Android may use native SDKs. Document which engine each target uses in one place (e.g. `mapview-desktop/README` successor section).

## Game loop (client responsibilities)

### Casual / default (client truth)

1. Load round / clue state from **local pool, bundled assets, or optional reference server** (or mock).
2. User places guess on map → **client** computes distance/score/XP vs **local golden truth** (`ground_truth` for the round). **Persist** the round outcome to the **per-`map_id` local leaderboard** (`rules/05-networking-leaderboard.md`, `rules/13-client-cache-and-data-plane.md`). **No** server score **`POST`** is required for non-ranked default play.
3. Show **success overlay** with **client-computed** distance/score/XP (single source of truth on device for non-ranked).
4. Navigate to **full results**; then **RANK** (or embedded ranks) with **`map_id`** per `rules/01-navigation-architecture.md` and **`05`**; shows **local** history (and optional **GET**-hydrated reference or community rows if the product enables those APIs), including **Human vs Human / vs Alien / vs Astronaut** facets and **AI vs golden answer** from **local resolution** and/or server reference payloads.

### Ranked missions (server truth)

1. **Start** ranked round via API → receive **clue manifest** + `round_ticket` (no client-held golden truth for that `round_id`; **during** the round, avoid on-device inference that could leak coordinates—`rules/06-server-vlm-tim-and-on-device-ml.md`).
2. User places guess → **POST** `guess_lat` / `guess_lon` + ticket; server returns **verified** distance/score.
3. Success overlay and results use **server payload** only for ranked numbers; hydrate **ranked** leaderboard segment per `05`.

For **batch Street View / LFM-VL hint materialization**, **progressive map zoom**, and **AI marker** phase—see **`10-terramesh-vlm-progressive-zoom-game-engine.md`** and **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`**. The **simplified default** is **primary still + narrative + one guess**; assists and zoom tiers remain **optional** (`docs/GAME-ENGINE.md` §7–9).

## Map markers (human, optional peer, AI)

- **`MapViewport`** must render **legibly distinct** layers for: **(1)** the local player’s **locked** guess, **(2)** an **optional peer-hint** marker shown **only** after **Reveal uplink** (async hint, **not** a lobby or multi-submit requirement), **(3)** the **AI** marker from **cached** `ai_lat`/`ai_lon` **after** the human phase ends (`docs/GAME-ENGINE.md` §10.1, §12.2). **Provisional** drag pins before confirm remain **self-only**.
- **PRO outputs are opt-in overlays only:** ad-hoc PRO `Coordinates` / mini-app outputs must not silently mutate shipped `ai_guesses` or ranked/non-ranked truth. If product lets a user publish a PRO output into gameplay, it must use a separate overlay source and show marker provenance such as **manifest** vs **PRO run**.
- **Non-ranked optional `POST .../guesses/record`** may accompany lock-in for server telemetry; it **does not** change map marker semantics (`rules/05-networking-leaderboard.md`).
- **Ranked:** Peer reveal **or** consuming **Street View / useful-hint assists** before `submit` **forfeits** verified ranked row—server-attested endpoints required (`docs/RANKED-MODE.md`, `rules/05-networking-leaderboard.md`).

## POI vs in-round guess

- **In-round guess** is the gameplay marker tied to **`round_id`** / lock-in semantics on the **active** map.
- **POI submission** (`rules/05-networking-leaderboard.md`) is a **separate** optional flow: user- or **device-sourced** coordinates for a **`map_id`** (suggest location, report issue, etc.). **Do not** conflate APIs unless product explicitly merges them; map UI should use **distinct** affordances (e.g. “Submit POI” vs “Lock in guess”).
