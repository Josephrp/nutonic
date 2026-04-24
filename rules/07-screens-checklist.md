# Screen checklist (implementation vs refs)

Each row: implement in **`commonMain`** unless a **platform actual** is noted. Pair **`code.html`** with **`screen.png`** for layout.

**Screen music (mandatory):** Per [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md), each shipped surface plays **one** identified background loop (`track_id`) and includes a **header music on/off** control wired to **`audio.music_master_enabled`** (same preference as SETUP → Audio). Crossfade on route change; bundle assets under shared resources — no CDN audio.

**SCAN hub (product default):** After splash + role, the **default main-shell tab is SCAN** (`rules/01-navigation-architecture.md`). **Mission selection (4c)**, **map / level selection (4b)**, **per-map leaderboard slice**, and **entry into gameplay (5)** live in this **one converged surface** — no separate **lobby** screen; **per-`map_id` local** leaderboards are the default (`docs/SOCIAL-AND-COMPETITION.md`, `rules/05-networking-leaderboard.md`).

| # | Screen | Stitch folder | BGM `track_id` (`docs/SCREEN-MUSIC-SPEC.md`) | Must include |
|---|--------|---------------|----------------|--------------|
| 1 | Splash | `splash_screen` | `music_splash` | Globe/brand, tagline, Initialize CTA, footer status line, build label from config; **header music toggle** |
| 2 | Authentication | `authentication` | `music_auth` | Identity + credential fields **optional path**; must be **skippable** for reference build (`rules/01-navigation-architecture.md`); server/status line if shown; **header music toggle** |
| 3 | Role selection | `role_selection` | `music_role` | **Three explicit role cards: Human, Astronaut, Alien** — perks copy, Initialize, protocol version; no ambiguous single “player” choice; **header music toggle** |
| 4 | Dashboard ( **INTEL** tab ) | `dashboard` | `music_intel` | XP, rank progress, primary play shortcut may jump to **SCAN** with last or featured `map_id`, memory stability, current session, daily protocols list; **header music toggle** |
| 4b | **Map / level selection** | *(primary content of **SCAN** hub; not a separate Map tab)* | `music_scan_hub` | **List or grid of maps/levels** with stable **`map_id`**; **narrative text box(es)** from **build-serialized** `prompts/` (`slot: map_select`, `docs/NARRATIVE-AND-PROMPTS.md`); **affordance to open per-map leaderboard** for the selected or highlighted map in **≤1 extra action** (sheet or navigate to **RANK** with `map_id`); **“Update”** reloads **local** rows and, if configured, refetches **optional** server aggregates (**auto-refetch off by default**—`rules/05-networking-leaderboard.md`); passes **`map_id`** into shared leaderboard composable (`rules/01-navigation-architecture.md`, `rules/05-networking-leaderboard.md`); **header music toggle** (shell header) |
| 4c | **Mission selection** | *(product screen; stitch may not exist—add as shell route)* | `music_scan_hub` | **Mission list** with **`mission_id`**; **narrative text boxes** (`slot: mission_select`); optional thumbnail; continues to map/level selection or directly to gameplay; **same** BGM as SCAN hub unless product splits a dedicated `track_id` later (document in `SCREEN-MUSIC-SPEC` revision table); **header music toggle** |
| 5 | World map gameplay | `world_map_gameplay` | `music_gameplay` | **Basemap** toggle (satellite / map / hybrid); **reference Mapbox still**; **expandable bottom-right modal**: search + **single primary guess submit**; HUD: **elapsed / budget** (count-up) and score preview as product needs; **narrative overlay modal**: authorial copy + **bundled pre-cached** assist lines + **user text input** (`rules/06-server-vlm-tim-and-on-device-ml.md`); lat/lng/elv; bottom shell; same **`map_id`** as selection + leaderboard scope; **header music toggle** |
| 6 | Success overlay | `success_overlay` | `music_success` | Post-guess summary, precision, XP, navigation to full results / map; **header music toggle** (or overlay top bar equivalent) |
| 7 | Final results | `final_results` | `music_results` | Mission score, tactical breakdown, level progression, **ranks** from **local** per-`map_id` history (plus **optional** community/`GET` section if product enables it) + **AI vs golden answer** from the resolved round; PvP facets **Human–Human, Human–Alien, Human–Astronaut, Alien–Astronaut** per `rules/05-networking-leaderboard.md`; play again / share; **header music toggle** |
| 8 | Settings / protocol ( **SETUP** tab ) | `settings_protocol` | `music_setup` | Profile block, security status, sliders, accessibility toggles, destructive actions styled per DESIGN; **header music toggle**; Audio sliders sync with [`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md) §6.7 |
| 9 | **PRO** (VLM tools, non-game) | **`refs/VLMExample/`** (port target) | `music_pro` | **Compose port** of the VLM example app: minimal shell, **not** the default geo-guess loop (`rules/01-navigation-architecture.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`); **map-first AOI picker** with movable pin is the primary coordinate entry, numeric lat/lon fields are advanced/accessibility only and stay in sync; production routes must not ship placeholder-only content; includes mini-app entries for FireWatch, OceanScout, LandShift, FloodPulse, and Brief Composer; **header music toggle** |

## PRO Mini-App Acceptance Rows

These rows refine screen **9** and are required before a PRO mini-app route can be considered production-ready. Stubs may exist during development, but a shipped route cannot be placeholder-only.

|Mini-app|Route token|Must include|
|---|---|---|
|**PRO dashboard**|`pro`|Shared `MapViewport` AOI picker as the primary input; single center pin with tap/pan/drag semantics; zoom/bbox sync; collapsed validated coordinate fields; `features.pro_jobs` gate-aware run controls; recent job refresh; polling with retry/backoff; merged artifact lists from `artifacts`, `analysis_artifacts`, `brief_artifacts`, and `on_device_payload.overlay_refs`.|
|**FireWatch**|`pro-firewatch`|Artifact-backed wildfire map overlay; burn/change mask or hotspot layer; hotspot list with confidence/evidence labels; status/error copy for STAC/cloud/worker failures; brief handoff. Placeholder copy alone fails acceptance.|
|**OceanScout**|`pro-oceanscout`|Compare/overlay view for vessel candidates and coastal context; observation coverage panel; normalized heatmap/incursion summaries; shoreline/confidence/evidence labels; explicit claim-safety limitations. Placeholder copy alone fails acceptance.|
|**LandShift**|`pro-landshift`|Artifact-backed before/after or classified overlay; transition matrix/top transitions; scene provenance and quality metadata; brief handoff. Placeholder copy alone fails acceptance.|
|**FloodPulse**|`pro-floodpulse`|Before/after flood extent view; inundation polygons or affected-area metrics; confidence/coverage warnings; brief handoff. Placeholder copy alone fails acceptance.|
|**Brief Composer**|`pro-brief`|Selectable source outputs from one or more PRO jobs; structured sections with source toggles; export/share affordance; clear provenance for generated claims. Placeholder copy alone fails acceptance.|

**RANK tab (shell):** Uses **`music_rank`** when the player is on the **RANK** destination; reuse **final_results** leaderboard composables — see [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md). **Header music toggle** required.

## Overlays and modals (from spec text)

- **Game launch overlay** (optional): **Solo / Multi / AI** only—**do not** surface a heavy **Easy / Medium / Hard** ladder; if “challenge” is needed, use **one** `assist_level` or mission metadata (`docs/GAME-ENGINE.md` §7). Implement as sheet/dialog **without** exceeding max navigation depth rule.
- **AI / assist**: entry near hint or overlay; narrative overlay **always** shows **bundled** SCAN hints + user text; **on-device VLM** is **mandatory only for the PRO tab** per **`refs/VLMExample/`** (`rules/06-server-vlm-tim-and-on-device-ml.md`).

## Leaderboard-only entry

- **RANK** tab reuses rows/components from **final_results** “Global ranks” for consistency (single composable, **multiple contexts**: **global** list + pick `map_id`, **per-`map_id`**, SCAN hub embed, results embed), with the **same** matchup and **AI vs truth** semantics (`rules/05-networking-leaderboard.md`). **Final results → RANK** must pass **`map_id`** for post-round context.

## String and content

- **Authorial narrative** lives under **`prompts/**/*.md`** and is **codegen’d** at build time (`docs/NARRATIVE-AND-PROMPTS.md`); **generated bundles** are not hand-edited.
- **Microcopy** and short UI labels may still use a **resource layer** (Compose Multiplatform resources or typed `String` table) for future localization.
