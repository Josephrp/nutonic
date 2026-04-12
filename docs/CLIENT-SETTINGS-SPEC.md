# NU:TONIC — Client settings specification

This document defines **user-facing settings** and **client-level configuration** for NU:TONIC Kotlin Multiplatform clients. It aligns with [`rules/02-design-system.md`](../rules/02-design-system.md), [`rules/06-server-vlm-tim-and-on-device-ml.md`](../rules/06-server-vlm-tim-and-on-device-ml.md), [`rules/08-ux-and-performance-footguns.md`](../rules/08-ux-and-performance-footguns.md), [`rules/13-client-cache-and-data-plane.md`](../rules/13-client-cache-and-data-plane.md), [`docs/GAME-ENGINE.md`](GAME-ENGINE.md), [`docs/RANKED-MODE.md`](RANKED-MODE.md), [`docs/SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md) (screen loops + header music control), and the **SETUP** (`settings_protocol`) screen intent in [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md).

**Audience:** client engineers (`commonMain` + platform actuals), UX, and anyone defining OpenAPI fields that mirror preferences sent to the server (only where explicitly allowed).

---

## 1. Goals and non-goals

### 1.1 Goals

- **Single preference model** across Android, iOS, Desktop, and Web (where shipped): same keys, semantics, and persistence tier.
- **Predictable behavior:** toggles must **actually change** rendering or inference routing (no dead switches) — per [`rules/02-design-system.md`](../rules/02-design-system.md) for accessibility and hint/ML rules below.
- **Trust clarity:** distinguish **cosmetic / comfort** settings from **ranked / anti-cheat** constraints so implementers do not accidentally expose server-held truth through local ML or remote hints.

### 1.2 Non-goals

- **OpenAPI field-by-field** definition (belongs beside the reference server contract).
- **Server-side operator config** (Gradio `/ops`, HF Jobs) — see [`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`](SERVER-AND-INFERENCE-ARCHITECTURE.md) and [`rules/12-python-gradio-terramind-server.md`](../rules/12-python-gradio-terramind-server.md).
- **Pixel layout** of SETUP — use `refs/stitch/settings_protocol/` as visual reference; this doc defines **behavior and data**.

---

## 2. Taxonomy: kinds of settings

| Kind | Definition | Typical persistence | Examples |
|------|------------|---------------------|----------|
| **User preferences** | Choices the player expects to control | `DataStore` / preferences / encrypted prefs for secrets | Audio, accessibility, hint visibility |
| **Session flags** | Reset or implied each cold start / match entry unless “remember” is on | In-memory + optional “remember last” user pref | Temporary ML route, one-shot “don’t show again” |
| **Client constants** | Build-time or deploy-time; not toggles in SETUP | `BuildConfig`, plist, env | `baseUrl`, Mapbox key id, `content_version` |
| **Policy-enforced (read-only in UI)** | Server or `rules` forbid user override in a given mode | N/A — show disabled control + explanation | Ranked: no local geo-inference on clue tensors |
| **Danger zone** | Destructive or irreversible | Immediate action or confirmation | Clear local leaderboards, factory reset |

**Parity rule:** Preference keys and default values live in **`commonMain`** (single source of truth). Platform code only provides **storage actuals** and **system setting sync** (e.g. read OS “reduce motion” as default).

---

## 3. Persistence and migration

- **Storage:** Use a **versioned** preferences blob (e.g. `nutonic_prefs_v1`) with a **`schema_version`** integer inside JSON or proto so migrations can rename keys without data loss.
- **Defaults:** Document **default** for every key in §6. First launch = defaults + optional OS import (§4.2).
- **Backup:** Local leaderboards and caches are **separate** from this spec’s preference store ([`rules/13`](../rules/13-client-cache-and-data-plane.md)); “factory reset” must declare whether it clears **prefs only** or **prefs + local game data**.

---

## 4. System integration

### 4.1 Platform accessibility (read on launch)

| OS / platform signal | Maps to internal keys (suggested) | Behavior |
|----------------------|-----------------------------------|----------|
| Reduce motion | `a11y.reduced_motion` **suggested default ON** if OS requests | When ON: disable or reduce parallax, particles, non-essential transitions; scanline overlay static or off ([`rules/02`](../rules/02-design-system.md), [`rules/08`](../rules/08-ux-and-performance-footguns.md)). |
| High contrast | `a11y.high_contrast` | Stronger outlines / ghost borders per DESIGN; never rely on color alone for state. |
| Font scale / large content | `a11y.large_data_rendering` (in-app) **or** derive from OS font scale | Scale typography and touch targets where product allows ([`rules/02`](../rules/02-design-system.md)). |

**Rule:** If the user toggles an in-app setting that **duplicates** OS behavior, **in-app wins** until “Reset to system defaults” is chosen (optional control).

### 4.2 Optional “follow system” switches

Suggested keys:

- `a11y.follow_system_motion` (boolean, default `true`) — when `true`, re-read OS reduce-motion when app resumes.
- `a11y.follow_system_contrast` (boolean, default `true`).

---

## 5. Trust modes and precedence (critical)

### 5.1 Modes

| Mode | Hint / ML constraints |
|------|------------------------|
| **Casual / reference (non-ranked)** | User may hide non-AI hints, hide AI/ground hints, and choose **local vs remote** assist subject to availability. Client-owned round truth ([`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §0). |
| **Ranked (active round)** | **SCAN** ranked: **primary** cached Mapbox still; **optional assists** (Street View text, useful-hint tiers) **forfeit** verified placement if used before submit ([`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §9, [`docs/RANKED-MODE.md`](RANKED-MODE.md)). **PRO** is a **separate** tab; product may **hide or dim** PRO entry while a ranked round is active for UX clarity. |
| **Post-round / POI proposal** | **PRO** on-device assist may apply to **structured POI** flows only when product enables ([`rules/06`](../rules/06-server-vlm-tim-and-on-device-ml.md)). |

### 5.2 Precedence order (highest wins)

1. **Regulatory / OS** (e.g. forced high contrast in enterprise builds)  
2. **Ranked active-round policy** (e.g. disables **PRO** shortcuts when product defines that UX)  
3. **Explicit in-app user override**  
4. **OS-suggested defaults** (when `follow_system_*` is true)  
5. **Product defaults** (§6)

---

## 6. Complete setting catalog

Keys use **dot notation** for clarity; implement as flat keys or nested structs as needed. Types: **bool**, **enum**, **float 0–1**, **int**, **string** (bounded length).

### 6.1 Identity and profile (SETUP — profile block)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `profile.display_name` | string | `""` | Optional handle for “YOU” on local boards ([`rules/05`](../rules/05-networking-leaderboard.md)); not a login identity. Max length e.g. 32; sanitize per OpenAPI when mirrored to server. |
| `profile.avatar_id` | string | product default | Cosmetic avatar or preset id. |
| `profile.show_rank_badge` | bool | `true` | Whether to show rank/level chip on profile card. |

**Role (mandatory product choice, not “account”):**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `game.role` | enum | **required before first SCAN** | `HUMAN` \| `ASTRONAUT` \| `ALIEN`. Set on **role selection** flow ([`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md)). **Also editable in SETUP** (“Change role”) so users can switch without re-onboarding. |
| `game.role_change_count` | int (telemetry, optional) | `0` | If product collects analytics only; not user-facing. |

**Authoritative stance:** Per [`rules/06-server-vlm-tim-and-on-device-ml.md`](../rules/06-server-vlm-tim-and-on-device-ml.md) §Alien / Human / Astronaut and [`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §6.1 **Role**, roles are **narrative and presentation** for fairness unless an ADR adds role-gated mechanics. The client may still apply **presentation-only** filters (copy salutation, icon set) from `prompts/` ([`docs/NARRATIVE-AND-PROMPTS.md`](NARRATIVE-AND-PROMPTS.md)). **Ranked** scoring stays **server-only**; **non-ranked** scoring stays **client math** with **no role-based multipliers** unless an ADR and OpenAPI document them—record any future exception in this table.

---

### 6.2 Narrative vs clue imagery

**Definitions (product vocabulary for UI strings):**

- **Narrative / non-clue UI:** Authorial **`prompts/`** copy, mission/map text, timer callouts — **not** smuggled substitutes for labeled assists ([`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §9–§11).
- **Primary location reference:** The **downsampled Mapbox still** composited in the reference layer—the baseline for placing a guess.
- **Assist UI (optional):** **Street View description** text and **useful-hint tiers** (three levels)—**collapsible** panels, **ranked forfeit** if consumed before submit when product ships those assists ([`docs/RANKED-MODE.md`](RANKED-MODE.md)).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `hints.show_non_ai` | bool | `true` | When `false`, hide **optional assist** chrome (Street View pack, useful-hint tiers); mission narrative may still follow product minimums. |
| `hints.show_ai_ground` | bool | `false` | When `true`, allow **Street View description** assist panel when bundle includes `streetview_hint_pack` ([`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §9). **Does not** disable mandatory engine events (e.g. **AI marker phase** still runs per [`docs/GAME-ENGINE.md`](GAME-ENGINE.md)). |
| `hints.ai_detail_level` | enum | `NORMAL` | Reserved for future assist modes. |
| `hints.rate_limit_multiplier` | float | `1.0` | Reserved for optional remote refresh paths. |

**Ranked:** Product may pin toggles for ranked shells; defaults stay aligned with **`docs/RANKED-MODE.md`**.

---

### 6.3 Local vs remote model usage (inference routing)

Per [`rules/06-server-vlm-tim-and-on-device-ml.md`](../rules/06-server-vlm-tim-and-on-device-ml.md): **SCAN** narrative uses **bundled** text; **PRO** tab ships **on-device** VLM (`refs/VLMExample/`); **TiM / TerraMind `_generate` / heavy EO** stay server-side. Users need clarity, not raw architecture.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ml.narrative_route` | enum | `BUNDLED_FIRST` | **`BUNDLED_FIRST`** — SCAN overlay uses **app-bundled** hint lines; optional **remote refresh** when online. **`REMOTE_FIRST`** — prefer **live** server-hydrated SCAN lines when configured (still not on-device on map). **`BUNDLED_ONLY`** — never fetch remote SCAN hints. |
| `ml.pro_tab_route` | enum | `AUTO` | Routing for **PRO** tab on-device vs server bundle stages ([`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md), [`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`](PRO-TAB-VLM-ORCHESTRATION-SPEC.md)). |
| `ml.allow_server_narrative` | bool | `true` | Master switch for **network-backed** SCAN hint refresh / intel copy during casual play. |
| `ml.on_device_enabled` | bool | `true` | When `false`, skip **PRO** on-device inference (save battery); **must not** block SCAN play (**bundled** hints still show) ([`rules/06`](../rules/06-server-vlm-tim-and-on-device-ml.md)). |
| `ml.max_local_tokens` | int | product default | Hard cap for local prompts (inject allowlisted context only). |
| `ml.show_inference_disclosure` | bool | `true` | When true, show one-line disclosure in overlay footer (“Local model” / “Network assist”) for transparency. |

**Ranked active round:** `ml.on_device_enabled` **forced off** for **PRO** while a ranked SCAN round is active; bundled SCAN copy unaffected + [`docs/RANKED-MODE.md`](RANKED-MODE.md).

**Remote definition:** HTTP(S) to NU:TONIC **game** or **inference** APIs per OpenAPI — **never** direct Hugging Face Hub or `hf` CLI on device ([`rules/13`](../rules/13-client-cache-and-data-plane.md)).

---

### 6.4 Map and gameplay presentation

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `map.default_basemap` | enum | `SATELLITE` | `SATELLITE` \| `ROADMAP` \| `HYBRID` per [`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §map. |
| `map.remember_last_viewport` | bool | `false` | Whether to restore pan/zoom between sessions (privacy consideration). |
| `map.show_coordinate_readout` | bool | `true` | Lat/lng/elv HUD line on gameplay ([`rules/07`](../rules/07-screens-checklist.md)). |
| `map.show_reference_still` | bool | `true` | Mapbox (or equivalent) still layer. |
| `map.guess_hit_slop_multiplier` | float | `1.0` | Scales invisible hit target for pin placement ([`rules/04-maps-and-gameplay.md`](../rules/04-maps-and-gameplay.md), [`rules/08`](../rules/08-ux-and-performance-footguns.md)); min/max clamp e.g. `[1.0, 2.5]`. |
| `gameplay.show_timer` | bool | `true` | **Cosmetic** elapsed / notional budget HUD (**count-up** vs `play_budget_ms`) when the mission defines a display limit—**diegetic only**; does **not** gate submit or fail rounds (`docs/GAME-ENGINE.md` §7.3). |
| `gameplay.show_score_preview` | bool | `true` | Non-authoritative preview before submit. |
| `gameplay.confirm_before_submit` | bool | `true` | Extra confirm step to reduce mis-taps. |

---

### 6.5 Narrative overlay and VLM UX

The **narrative overlay** is **always available** ([`rules/06`](../rules/06-server-vlm-tim-and-on-device-ml.md)); user settings control **visibility and noise** of **bundled / remote** assist lines on SCAN, not removal of the surface.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `narrative.overlay_default_open` | bool | `false` | Whether glass narrative opens expanded on round start. |
| `narrative.preserve_user_notes` | bool | `true` | Persist user-typed notes in overlay across app restarts (local only). |
| `narrative.stream_order` | enum | `AUTHOR_FIRST` | `AUTHOR_FIRST` \| `INTERLEAVE` — ordering of authorial vs model lines in UI. |

---

### 6.6 Progressive zoom (optional product mode)

When [`docs/GAME-ENGINE.md`](GAME-ENGINE.md) §8.3 / [`rules/10`](../rules/10-terramesh-vlm-progressive-zoom-game-engine.md) is enabled:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `zoom.user_enabled` | bool | `true` | Participate in progressive zoom tier advances (when `false`, client stays at tier 0 or mission default until guess — product-defined). |
| `zoom.animate_tier_changes` | bool | `true` | Respects `a11y.reduced_motion` when true. |

---

### 6.7 Audio (SETUP — stitch-aligned + screen music)

Per **[`docs/SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md)**: the app ships **one bundled background loop per primary route**; **every shipped screen** exposes a **music on/off** control in the **header chrome** that toggles the **`audio.music_master_enabled`** key below (same store as SETUP — no duplicate state).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `audio.music_master_enabled` | bool | `true` | **Global** music mute. When `false`, no BGM plays on any screen; header toggle and SETUP must reflect the same value. SFX (`audio.sfx_volume`) is **unaffected** unless product adds a separate “mute all” (not default). |
| `audio.music_volume` | float 0–1 | `0.85` | Music channel gain when `audio.music_master_enabled` is true. |
| `audio.sfx_volume` | float 0–1 | `0.42` | SFX channel (defaults may match stitch reference). |
| `audio.mute_when_backgrounded` | bool | `true` | Platform-appropriate pause/duck when app is backgrounded; **does not** flip `audio.music_master_enabled`. |

---

### 6.8 Accessibility (in-app, SETUP)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `a11y.high_contrast` | bool | `false` | Stitch “High contrast mode”; must change contrast tokens ([`rules/02`](../rules/02-design-system.md)). |
| `a11y.reduced_motion` | bool | `false` | Stitch “Reduced motion”; disables heavy motion ([`rules/08`](../rules/08-ux-and-performance-footguns.md)). |
| `a11y.large_data_rendering` | bool | `false` | “Large data rendering” — scale UI density / numeric tables ([`rules/02`](../rules/02-design-system.md)). |
| `a11y.screen_reader_optimizations` | bool | `false` | Extra semantics / grouping for TalkBack / VoiceOver (implement per platform). |

---

### 6.9 Privacy, telemetry, and social

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `privacy.allow_analytics` | bool | per product | Crash + usage analytics; gated by store policy. |
| `privacy.allow_optional_community_sync` | bool | `false` | When true, allows **opt-in** community leaderboard `POST` where OpenAPI exists ([`rules/05`](../rules/05-networking-leaderboard.md)). |
| `privacy.show_last_fetched_on_leaderboard` | bool | `true` | Show last refresh time for optional server slices ([`rules/05`](../rules/05-networking-leaderboard.md)). |

---

### 6.10 Network and data refresh

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `network.api_base_url_override` | string? | `null` | Debug / staging only; gated by build flavor ([`rules/05`](../rules/05-networking-leaderboard.md)). |
| `network.auto_refetch_leaderboard` | bool | `false` | **Auto-refetch off by default** per [`rules/05`](../rules/05-networking-leaderboard.md); user can opt in if product allows. |

---

### 6.11 Leaderboard and local data (comfort)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `leaderboard.default_map_filter` | string? | `null` | Last selected `map_id` for RANK tab convenience. |
| `leaderboard.show_ai_vs_truth_track` | bool | `true` | Visibility of **AI vs golden** dimension ([`rules/05`](../rules/05-networking-leaderboard.md)). |

**Danger zone (explicit confirmations):**

| Key / action | Description |
|--------------|-------------|
| `data.clear_local_leaderboards` | Action: wipe per-`map_id` local rows ([`rules/13`](../rules/13-client-cache-and-data-plane.md)). |
| `data.factory_reset` | Action: reset **all** prefs in this spec + optional caches per product confirmation copy (stitch “FACTORY RESET”). |

---

### 6.12 Account (when gated features exist)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `auth.biometric_preferred` | bool | `false` | Use biometric app unlock for returning to app (platform actual). |
| `auth.remember_jwt` | bool | `true` | Store tokens in secure storage when ranked/login used ([`rules/05`](../rules/05-networking-leaderboard.md)). |

---

### 6.13 Developer and QA (never in store release without compile guard)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `debug.mock_api` | bool | `false` | Seeded leaderboard / rounds ([`rules/05`](../rules/05-networking-leaderboard.md) `MockApi`). Compile-time strip in release if required. |
| `debug.show_fps` | bool | `false` | Performance overlay. |

---

## 7. SETUP screen grouping (recommended UX)

Map sections to [`refs/stitch/settings_protocol/`](../refs/stitch/settings_protocol/) **structure**:

1. **Profile** — `profile.*`, shortcut to **change role** (`game.role`).
2. **Gameplay & hints** — `hints.*`, `gameplay.*`, `zoom.*` (if enabled).
3. **Models & assist** — `ml.*` (plain-language labels).
4. **Map display** — `map.*`.
5. **Narrative & VLM** — `narrative.*` (subset overlaps with hints; keep one subsection to avoid duplication).
6. **Audio** — `audio.*` (include **music master** + volumes; link to [`SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md) for route → track table).
7. **Accessibility** — `a11y.*` + link to OS settings.
8. **Privacy & data** — `privacy.*`, `network.*` (non-debug), leaderboard comfort keys.
9. **Account / security** — `auth.*` + sign-in/out when product ships account.
10. **Danger zone** — `data.*` actions, **UPLOAD CONFIG** equivalent = sync settings backup if product ships cloud backup (optional).

---

## 8. Implementation checklist

- [ ] All keys in §6 defined in **`commonMain`** data class / DataStore schema with **`schema_version`**.  
- [ ] SETUP toggles **read and write** the same store; **no** parallel ad-hoc `rememberSaveable` for persisted prefs.  
- [ ] **Ranked** path: integration tests that verify **forbidden** combinations (e.g. local geo model on ranked active round) are **impossible** via UI + ViewModel guards.  
- [ ] **Hints off** still allows **minimum** mission legibility (tutorial copy) if product requires.  
- [ ] **Accessibility:** changing `a11y.*` triggers immediate recomposition with measurable effect ([`rules/02`](../rules/02-design-system.md)).  
- [ ] **Parity:** Desktop/Web lack a biometric toggle → hide or disable with explanation.  
- [ ] **Screen music:** Route → `track_id` per [`SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md); **header music toggle** on every checklist screen wired to `audio.music_master_enabled`.  
- [ ] Strings: resource table for localization; **no** user-facing raw preference keys.

---

## 9. Related documents

| Document | Relevance |
|----------|-----------|
| [`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md) | SETUP tab placement, role flow |
| [`rules/02-design-system.md`](../rules/02-design-system.md) | Motion, glass, typography |
| [`rules/06-server-vlm-tim-and-on-device-ml.md`](../rules/06-server-vlm-tim-and-on-device-ml.md) | VLM, on-device, ranked ML locks |
| [`rules/13-client-cache-and-data-plane.md`](../rules/13-client-cache-and-data-plane.md) | No Hub on device, local cache |
| [`docs/GAME-ENGINE.md`](GAME-ENGINE.md) | Basemap, zoom, assist_level, phases |
| [`docs/RANKED-MODE.md`](RANKED-MODE.md) | Ranked overrides |
| [`docs/NARRATIVE-AND-PROMPTS.md`](NARRATIVE-AND-PROMPTS.md) | Non-AI narrative source |
| [`docs/SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md) | One BGM loop per screen, header music toggle, asset paths |

---

## 10. Revision history

| Date | Change |
|------|--------|
| 2026-04-08 | Initial client settings spec (user + client prefs, hints, AI/ground hints, local/remote ML, role, ranked precedence). §6.7 extended with `audio.music_master_enabled`, [`SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md), SETUP grouping + implementation checklist. |
