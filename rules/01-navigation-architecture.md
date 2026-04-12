# Navigation architecture (canonical)

## Rule: single source of truth for routes

Define **one** navigation graph in shared code (e.g. sealed classes or typed routes in `commonMain`). **Do not** fork different tab sets per platform.

## Canonical route IDs vs display labels (product decision)

- Use **stable route IDs** in code (e.g. sealed `MainTab` or typed routes): `ScanHub`, `Intel`, `Rank`, `Setup`, `Pro`.
- **In-app bottom bar labels** use tactical copy (stitch-aligned): **SCAN**, **INTEL**, **RANK**, **SETUP**, **PRO** — not legacy prose (“Home”, “Map”, “Play”, “Leaderboard”, “Settings”). Document the **ID → label** mapping **once** next to the route enum; strings elsewhere should reference the enum or shared label table.
- Older docs or mock filenames may still say “dashboard / Home”; treat **INTEL** as the canonical tab for that surface.

## Primary shell: five bottom destinations

The persistent bottom bar has **five** items:

1. **SCAN** (`ScanHub`) — **Single converged game hub** (replaces separate **Map** and **Play** tabs): **map / level selection** (`map_id`), **scan** / play affordances, **map-scoped leaderboard** slice, mission narrative hooks, and navigation into **world map gameplay** — **one logical shell** (segments, pager, or sheets; respect **max depth** in `Depth limit` below). This is the **first** destination after splash + role (`Required flows`).
2. **INTEL** (`Intel`) — Dashboard: XP, rank progress, memory stability, daily protocols, current session (stitch `dashboard`).
3. **RANK** (`Rank`) — **Global** leaderboard entry: show **global** aggregates and an **explicit prompt / UI to pick a `map_id`**, then map-scoped boards, role filters, and matchup dimensions (`rules/05-networking-leaderboard.md`). From **RANK**, after the player picks a map, **Play** / **Scan** must enter **SCAN** with that **`map_id`** preloaded — same composable family as the per-map slice inside SCAN.
4. **SETUP** (`Setup`) — Protocol configuration, audio, accessibility, optional display name (stitch `settings_protocol`). **No mandatory account** for casual paths.
5. **PRO** (`Pro`) — **Non-game** surface: **coordinate info dashboard**—user sends **WGS84** to the **game server**, which returns a **materialized** bundle (Mapbox + optional Sentinel-2, **`tim_modality_outputs`** for all configured **`tim_modalities`**, optional **`_generate`** summary) for the client to combine with **on-device** VLM (**caption + labeled bboxes**) in a **layered** result card (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). Implemented via the **VLMExample** on-device port in Compose Multiplatform. **Not** part of the default geo-guess loop; TerraMesh-backed features may **later** extend here (`rules/10-terramesh-vlm-progressive-zoom-game-engine.md`). On-device ML requirements still apply per `rules/06-server-vlm-tim-and-on-device-ml.md`.

**Visually elevated node:** Per **`docs/DESIGN.md`** §5 (Navigation), the bottom bar elevates the **dominant game entry** — **default:** elevate **SCAN** (center bloom / primary affordance). If product moves the bloom to an in-SCAN FAB instead, document in the same route enum comment.

**Active tab indicator:** A **short line above the icon** (not below), per **`docs/DESIGN.md`** §5.

**Social:** Async **`map_id`** competition, **POI share**, and leaderboards only (`docs/SOCIAL-AND-COMPETITION.md`, `rules/05-networking-leaderboard.md`).

## Player roles (mandatory clarity)

- After splash, the flow must make it **obvious** that the player **chooses one of three roles**: **Human**, **Astronaut**, or **Alien** (role selection screen; stitch `role_selection`). Copy and icons must not collapse roles into a single generic “player.”
- **Roles are not login identities** — no separate authentication **per role**.

## Authentication (game server session, ranked, store writes)

- **No global blocking user-account sign-in** before the main shell for default play.
- **Game server token:** On first use of **hydration / leaderboard / manifest / POI** APIs, the client obtains a **short-lived session JWT** (device-bound) so the server can **rate-limit** and **cache** expensive work (`rules/05-networking-leaderboard.md`, `rules/00-product-intent.md`). This is **not** a social login wall.
- **Ranked / store / PRO jobs:** **JWT** (and official-client registration where applicable) is required per OpenAPI for **ranked** **start/submit**, **store-gated** writes, **PRO** materialization when gated, and **optional accounts** — see `rules/05-networking-leaderboard.md`. **Not** tied to Human/Astronaut/Alien selection.
- Stitch **authentication** UI remains **opt-in** for **account** flows; **silent** session bootstrap may run in the shell background without blocking **SCAN** entry.

## Stitch and legacy naming

- Product **adopts** **SCAN / INTEL / RANK / SETUP / PRO** as the **real** tab labels. Earlier interface-spec wording (“Home, Map, Play, Leaderboard, Settings”) is **deprecated** for IA; map prose mentally: Home → **INTEL**, Map+Play → **SCAN**, Leaderboard → **RANK**, Settings → **SETUP**, **PRO** is the VLM tools surface.

## Depth limit

**Maximum two levels** of navigation beyond a root tab for core flows (per spec footgun). Prefer overlays/sheets for mode pickers (solo / multi / AI) instead of deep stacks.

## Required flows (order)

1. Splash → optional **Initialize** CTA  
2. **Role selection** → player confirms **Human / Astronaut / Alien** (required for product clarity).  
3. **Optional** authentication — **only** when engaging **ranked** missions, store-gated writes, or account; **never** a mandatory wall before shell for default play.  
4. Main shell (tabs) → **default tab is SCAN** (converged map selection, leaderboard slice, play entry) — **not** INTEL first.  
5. **SCAN** → mission / map narrative (`prompts/`, `docs/NARRATIVE-AND-PROMPTS.md`) → **world map gameplay** → success overlay → **final results**; **final results must deep-link to RANK** with the **same `map_id`** as the finished round for leaderboard context (`rules/05-networking-leaderboard.md`).  
6. **RANK** → global list + user picks **`map_id`** → **Play** / **Scan** navigates to **SCAN** with that `map_id` (reuse leaderboard composables per `05`).  
7. **SETUP** and **PRO** persist across sessions where product stores preferences; **PRO** tracks the **coordinate dashboard** + **`refs/VLMExample/`** on-device port (`rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`).

Deep links (if added) must resolve into this graph without a third parallel navigation system.

## Screen music (BGM) vs tab / route

Background music **track** follows the **active primary surface** per [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md): e.g. **SCAN** hub segments use `music_scan_hub`, tab switch to **INTEL** / **RANK** / **SETUP** / **PRO** swaps to the corresponding `track_id`. **Every** shell and pre-shell screen keeps the **header music on/off** control (global `audio.music_master_enabled`); see [`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md) §6.7.
