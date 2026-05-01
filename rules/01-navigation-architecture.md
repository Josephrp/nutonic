# Navigation architecture (canonical)

## Rule: single source of truth for routes

Define **one** navigation graph in shared code (e.g. sealed classes or typed routes in `commonMain`). **Do not** fork different tab sets per platform.

## Canonical route IDs vs display labels (product decision)

- Use **stable route IDs** in code (e.g. sealed `MainTab` or typed routes): `ScanHub`, `Rank`, `Setup`, `Pro`.
- **In-app bottom bar labels** use tactical copy (stitch-aligned): **SCAN**, **RANK**, **SETUP**, **PRO** — not legacy prose (“Home”, “Map”, “Play”, “Leaderboard”, “Settings”). Document the **ID → label** mapping **once** next to the route enum; strings elsewhere should reference the enum or shared label table.
- Legacy token **`Intel`** in URLs and bookmarks resolves to **`Rank`** so fused behavior stays backward compatible.

## Primary shell: four bottom destinations

The persistent bottom bar has **four** items (**INTEL** merged into **RANK**):

1. **SCAN** (`ScanHub`) — **Single converged game hub** (replaces separate **Map** and **Play** tabs): **map / level selection** (`map_id`), **scan** / play affordances, mission narrative hooks, and navigation into **world map gameplay** — **one logical shell** (segments, pager, or sheets; respect **max depth** in `Depth limit` below). Community leaderboard detail lives under **RANK** (link from SCAN), not duplicated on SCAN. This is the **first** destination after splash + role (`Required flows`).
2. **RANK** (`Rank`) — **Fused progress + leaderboards**: session progress and honest local stats (`LocalNonRankedLeaderboardRepository`), community / ranked boards for the focused map, and entry to **global** aggregates (**RankGlobal** detail when needed). Legacy **IntelDashboard** detail remains encoded for deep links but surfaces under the **RANK** tab for BGM and UX.
3. **SETUP** (`Setup`) — Protocol configuration, audio, accessibility, display name (stitch `settings_protocol`). **No mandatory account** for casual paths.
4. **PRO** (`Pro`) — **Non-game** surface: **coordinate info dashboard** (`ProCoordinateDashboard`)—user sends **WGS84** to the **game server**, which returns a **materialized** bundle (Mapbox + optional Sentinel-2, **`tim_modality_outputs`** for all configured **`tim_modalities`**, optional **`_generate`** summary) for the client to combine with **on-device** VLM (**caption + labeled bboxes**) in a **layered** result card (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). Implemented via the **VLMExample** on-device port in Compose Multiplatform. **Not** part of the default geo-guess loop; TerraMesh-backed features may **later** extend here (`rules/10-terramesh-vlm-progressive-zoom-game-engine.md`). On-device ML requirements still apply per `rules/06-server-vlm-tim-and-on-device-ml.md`.

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
- There is **no separate onboarding “authentication” route** in the default checklist; optional account flows may use **SETUP** or future deep links without blocking **SCAN** entry.

## Stitch and legacy naming

- Product adoptees **SCAN / RANK / SETUP / PRO** as the **real** tab labels; earlier interface-spec wording (“Home, Map, Play, Leaderboard, Settings”) is **deprecated** for IA; map prose mentally: progress + leaderboards → **RANK**, Map+Play → **SCAN**, Settings → **SETUP**, **PRO** is the VLM tools surface.

## Depth limit

**Maximum two levels** of navigation beyond a root tab for core flows (per spec footgun). Prefer overlays/sheets for mode pickers (solo / multi / AI) instead of deep stacks.

## Required flows (order)

1. Splash → optional **Initialize** CTA  
2. **Role selection** → player confirms **Human / Astronaut / Alien** and **display name** (required for product clarity).  
3. Main shell (tabs) → **default tab is SCAN** (converged map selection, play entry) — **not** RANK first.  
4. **SCAN** → mission / map narrative (`prompts/`, `docs/NARRATIVE-AND-PROMPTS.md`) → **world map gameplay** → success overlay → **final results**; **final results must deep-link to RANK** with the **same `map_id`** as the finished round for leaderboard context (`rules/05-networking-leaderboard.md`).  
5. **RANK** → local progress + community boards for the focused map + optional global entry (**RankGlobal**); **Play** / **Scan** navigates to **SCAN** with the chosen **`map_id`** (reuse leaderboard composables per `05`).  
6. **SETUP** and **PRO** persist across sessions where product stores preferences; **PRO** opens the **coordinate dashboard** + **`refs/VLMExample/`** on-device port (`rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`).

Deep links (if added) must resolve into this graph without a third parallel navigation system.

## Screen music (BGM) vs tab / route

Background music **track** follows the **active primary surface** per [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md): e.g. **SCAN** hub segments use `music_scan_hub`, tab switch to **RANK** / **SETUP** / **PRO** swaps to the corresponding `track_id`. **Every** shell and pre-shell screen keeps the **header music on/off** control (global `audio.music_master_enabled`); see [`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md) §6.7.
