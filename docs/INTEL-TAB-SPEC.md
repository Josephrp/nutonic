# NU:TONIC — INTEL tab specification

**Status:** Normative product and engineering specification for the **INTEL** shell destination (`rules/01-navigation-architecture.md`, route id **`Intel`**, label **INTEL**).  
**Date:** 2026-04-12  
**Audience:** Compose Multiplatform engineers, narrative/prompt owners, API designers, UX and audio.

**Authority:** Binds to `rules/00-product-intent.md`, `rules/01-navigation-architecture.md`, `rules/02-design-system.md`, `rules/05-networking-leaderboard.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`, `rules/07-screens-checklist.md`, `rules/08-ux-and-performance-footguns.md`, `rules/13-client-cache-and-data-plane.md`, `docs/DESIGN.md`, `docs/GAME-ENGINE.md`, `docs/NARRATIVE-AND-PROMPTS.md`, `docs/INTEL-SCORING-AND-PROGRESSION-SPEC.md`, `docs/SCREEN-MUSIC-SPEC.md`, `docs/CLIENT-SETTINGS-SPEC.md`, `docs/RANKED-MODE.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md`, and layout reference `stitch/dashboard/code.html` (visual only — **not** runtime HTML).

---

## 1. Purpose and product role

### 1.1 What INTEL is

**INTEL** is the player’s **persistent command deck**: progress, continuity, light objectives, and **one-tap return to play**—without duplicating the full **SCAN** hub (mission/map pick, embedded leaderboard, world map). It answers: *“How am I doing overall? What should I do next? Can I jump back into the field?”*

| Dimension | INTEL | SCAN | RANK | PRO |
|-----------|-------|------|------|-----|
| **Primary job** | Progress + continuity + optional dailies | Pick mission/map, play rounds, per-map slice | Global and per-`map_id` leaderboard browsing | Non-game EO / VLM tooling |
| **Default after shell** | No — **SCAN** is default (`rules/01`) | Yes | No | No |
| **Ground truth for rounds** | Does not own round secrets | Owns active round UX for non-ranked | Displays aggregates / filters | N/A |
| **Auth gate** | None for reference browse (`rules/05`) | Same | Same | Optional JWT for materialize when shipped |

### 1.2 Creative stance (“Neon Relic” alignment)

INTEL uses the same **void + signal** language as `docs/DESIGN.md`: glass panels, **tonal stacking**, thin **primary** progress lines, **tertiary** success accents for “stable” readings. It should feel like **status telemetry** and **briefing**, not a second game map. **Glow** stays concentrated on **PLAY NOW** and primary CTAs (`rules/02`, `rules/08`).

### 1.3 Stitch legacy vs canonical shell

Reference mock `stitch/dashboard/code.html` still shows bottom labels **HOME / MAP / PLAY**. **Shipping product** uses **`ScanHub` / `Intel` / `Rank` / `Setup` / `Pro`** with **SCAN** elevated as the dominant play node (`rules/01`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md` §5.8). When porting visuals, **replace** legacy tab labels and icon semantics: INTEL uses **`home`** only as an **icon** option for the INTEL tab if design approves — the **string** must read **INTEL**, not HOME (`docs/NU_TONIC_ARTIFACT_REFERENCE.md` §7).

---

## 2. Scope

### 2.1 In scope (v1 INTEL)

- **Header:** NU:TONIC wordmark cluster, **global music on/off** (`docs/SCREEN-MUSIC-SPEC.md`), optional profile entry, **XP summary chip** (numeric + label).
- **Rank progress:** Tier name (e.g. product ladder) + **percent toward next tier** + thin progress bar (`stitch/dashboard` pattern).
- **PLAY NOW:** Large circular CTA; navigates to **SCAN** with **`map_id`** = last played, featured, or explicit product default; must respect **max navigation depth** (`rules/01`).
- **Memory stability:** Single **readout** + short explanatory line; value derived from **client-held** recent performance (see §6).
- **Current session:** Card summarizing **in-progress or last finished** play context **without** implying **live opponents**, **rooms**, **queues**, or **synchronized sessions**—copy stays **solo / async** on a shared **`map_id`** (`docs/SOCIAL-AND-COMPETITION.md`, §10 below).
- **Daily protocols:** Checklist of **small, completable** objectives with XP rewards; progress persisted locally; optional server-fed copy rotation.
- **BGM:** `music_intel` on this tab; crossfade on leave (`docs/SCREEN-MUSIC-SPEC.md`).

### 2.2 Explicitly out of scope (unless ADR)

- **Lobby / room codes / opponent matchmaking UI** — **not** in product scope; competition stays **async** on **`map_id`** (`docs/SOCIAL-AND-COMPETITION.md`).
- **Raw map interaction** — belongs on **SCAN** / world map (`rules/04`).
- **Full VLM chat** — **PRO** tab and map overlay (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `rules/06`).
- **Revelation of ranked secret coordinates** on INTEL — forbidden (`docs/RANKED-MODE.md`, §3.1 below).

### 2.3 Deferred / high-potential (roadmap)

See **§17**. Includes: INTEL **card deck** from satellite caption service, weekly cycles, streak heatmaps, faction **flavor-only** intel drops, cross-device sync of progress (account-backed).

---

## 3. Screen layout (normative regions)

Order top → bottom (scrollable **main** column). Spacing and tokens follow `docs/DESIGN.md` and `docs/NU_TONIC_ARTIFACT_REFERENCE.md` §6 row 4.

| Region | Purpose | Key behaviors |
|--------|---------|----------------|
| **App bar** | Brand + quick stats + music + optional account | XP chip **truncates** with tabular figures; music toggles `audio.music_master_enabled` |
| **Rank progress** | Long-horizon engagement | Copy: `Rank Progress: {Tier}` + `%`; bar = `filled / threshold` for current tier |
| **PLAY NOW** | Primary action | **~100 ms** press feedback (`rules/08`); navigates to SCAN with resolved `map_id` |
| **Memory stability** | Emotional + mechanical feedback | Glass panel; gradient meter optional; subcopy from `intel_card` or static pool |
| **Current session** | Continuity | Shows **mission title**, **map_id** or human title, **elapsed** or **last result** summary, **Resume** / **Open sector** → SCAN or gameplay if round incomplete |
| **Daily protocols** | Objectives | Rows: icon state (pending / in progress / done), title, subtitle, XP reward; optional per-row micro-progress |

**Accessibility:** All tappable rows **≥ 48 dp**; meter values exposed to Talk Back / VoiceOver; reduced motion disables **ping** on “live” dots and heavy parallax on session hero image.

---

## 4. Domain model and trust

### 4.1 Client authority

For **non-ranked** play, **XP**, **tier progress**, **memory stability**, **daily protocol completion**, and **session summaries** are computed and stored in **`commonMain`** (or persisted via platform storage through a shared repository). They are **not** anti-cheat signals for global competition (`docs/GAME-ENGINE.md` §0, `rules/00-product-intent.md`).

**Ranked:** INTEL may show **server-returned** aggregates *after* **`submit`** resolves (e.g. “Last ranked: Silver +12 RP”). **In-flight:** use **catalog** titles and **cosmetic** session/timer copy (`docs/GAME-ENGINE.md` §7.3)—**not** **verified** ranked score rows until the server responds. **PRO** tab stays a **separate** shell destination from active SCAN play (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §3).

### 4.2 Versioning

Persist **`ruleset_version`** / **`engine_version`** (or product **`progression_version`**) alongside saved progress so migrations can re-scale XP without corrupting saves (`docs/GAME-ENGINE.md` §6.2).

### 4.3 Role (Human / Astronaut / Alien)

Roles affect **copy and iconography** on INTEL (salutations, optional `intel_card` filter in `docs/NARRATIVE-AND-PROMPTS.md`). They **do not** change core XP math unless an **ADR** and OpenAPI say otherwise (`rules/06`, `docs/GAME-ENGINE.md` §13.1).

---

## 5. Metrics definitions (implementer-facing)

**Normative bindings, ranked vs engagement tier separation, mock field mapping, and memory-stability bands:** `docs/INTEL-SCORING-AND-PROGRESSION-SPEC.md`.  
Exact constants are **product knobs**; shapes below are normative summaries.

### 5.1 XP (`xp_total`)

- **Sources (examples):** round completion, distance bands, daily protocol claims, optional **first clear** of a map. Each grant carries **`source`**, **`amount`**, **`map_id`?**, **`round_id`?**, **`idempotency_key`** so retries do not double-award.
- **Display:** Integer in app bar; format with locale grouping.

### 5.2 Rank tier (`progression_tier`)

- **Concept:** Ordered ladder (e.g. Iron → Silver → …) driven by **`xp_total`** or a separate **rank_points** pool if product splits “cosmetic rank” from XP.
- **Bar:** `progress_in_tier = clamp01((xp_total - tier_floor) / (tier_ceil - tier_floor))`.

### 5.3 Memory stability (`memory_stability_0_100`)

**Recommended default formula (non-ranked):** rolling window of last **`N`** completed rounds (e.g. `N = 10`), map **median percentile** of precision vs that player’s history on those maps, mapped to **0–100** with soft saturation so one bad round does not tank the meter.  
**Labeling:** Pair numeric with qualitative band (e.g. `92% SAFE`) for diegetic tone.

**Optional server flavor:** Server may supply **replacement subcopy** only (no numeric obligation) via manifest; **length-capped** per OpenAPI (`rules/05`).

### 5.4 Daily protocols

Each **protocol** has: `protocol_id`, `title`, `description`, `xp_reward`, `state` (`locked` | `active` | `completed` | `claimed`), `progress_current`, `progress_target`, `reset_anchor` (UTC midnight or rolling 24h — **pick one product-wide** and document in settings copy).

**Completion:** On claim, apply XP with **idempotency**; mark `claimed`; animate check state.

---

## 6. Narrative and content (`prompts/`)

### 6.1 Slots (`docs/NARRATIVE-AND-PROMPTS.md`)

| Slot | Use on INTEL |
|------|----------------|
| **`intel_card`** | Memory stability title/subcopy, sector flavor, optional warnings (“Uplink variance high”) |
| **`mission_select` / `map_select`** | Not primary on INTEL; may appear if INTEL embeds a **compact** “next mission” teaser (optional) |
| **Server / job hooks** | `prompts/llm/daily_protocol_flavor.md` for rotating one-liners; **`content_version`** on fetch (`rules/13`) |

### 6.2 Labeling generated vs authorial

Apply **`docs/NARRATIVE-AND-PROMPTS.md` §8** labels in UI where ambiguity exists: **Operator brief** (bundled), **Signal assist** (server), **Local inference** (on-device) — INTEL should use **brief** + **Signal assist** only if server lines appear; default bundled.

---

## 7. Networking and hydration

### 7.1 Local-first default

INTEL **must render offline** from last persisted snapshot: XP, tier, memory stability, dailies state, last session card.

### 7.2 Optional HTTP (OpenAPI when shipped)

Illustrative resources (names may change):

| Endpoint | Role |
|----------|------|
| `GET /api/v1/intel/summary` | Optional **Signal assist** strings, featured `map_id`, server time for daily reset |
| `GET /api/v1/intel/cards` | Optional **card deck** (EO captions, mission teases) with **`ETag`** |
| `POST /api/v1/intel/dailies/{id}/claim` | Optional server-authoritative claim for cross-device sync — **idempotent** |

**Rules:** No ranked golden coordinates; reject unknown JSON keys; cap strings (`rules/05`). **Auto-refresh off by default** on INTEL (`rules/08` footgun 3) — user pull-to-refresh or tab re-select may refetch.

### 7.3 Satellite / EO “intel cards” (optional)

When product enables EO-backed briefing, the game server may attach **short captions** from **`inference/lfm_vl_satellite_caption_service`** (`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.2, `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`). Cards are **read-only**, **cached**, and **never** substitute SCAN round truth.

---

## 8. Actions and navigation

### 8.1 PLAY NOW

**Resolve order (recommended):**

1. If **round in progress** (`PLAY` phase with unsent guess or unsubmitted lock-in per engine rules), navigate **World map gameplay** for that `map_id` / `round_id`.
2. Else if **last played `map_id`** exists, navigate **SCAN** hub with that map focused / preselected.
3. Else navigate **SCAN** hub **default** segment (e.g. featured mission).

All transitions count toward **depth limit**; prefer **single** push or tab switch + args (`rules/01`).

### 8.2 Resume (Current session)

- **In-progress round:** Primary control **Resume** → gameplay route.
- **Idle:** **Open sector** → SCAN with `map_id`; optional **Clear** to dismiss card (local only).

### 8.3 Daily protocol row tap

- If incomplete and actionable → deep link to **SCAN** (specific map/mission) or show **sheet** explaining the task.
- If **completed** but unclaimed → **Claim** action + XP flyout.
- If **claimed** → disabled or shows check; no duplicate claim.

### 8.4 Cross-links from other surfaces

- **Final results** may expose **“Intel debrief”** CTA → INTEL with scroll target **Memory stability** (optional).
- **SETUP → Change role** returns player to role selection; INTEL copy refreshes from `PromptBundle` on return.

---

## 9. Audio and settings

- **Track:** `music_intel` (`docs/SCREEN-MUSIC-SPEC.md`).
- **Header music control:** Required on INTEL (`rules/07`).
- **Volume:** Scales with `audio.music_volume`; respects `audio.mute_when_backgrounded` (`docs/CLIENT-SETTINGS-SPEC.md` §6.7).

---

## 10. UX footguns (INTEL-specific)

1. **False multiplayer cues** — Avoid “squad”, “queue”, “lobby”, “party”, “matchmaking”, “live session”, or live opponent counts. **Do not** imply **push/stream** transport or **waiting on other humans**; INTEL is **telemetry + continuity** for **solo-first** play with **async** comparison on **`map_id`** (`docs/GAME-ENGINE.md` §14, `docs/SOCIAL-AND-COMPETITION.md`). Prefer **sector / uplink / async board** language.
2. **Stale session card** — Show **timestamp** (“Last uplink: 14:02”) or **relative** time; clear when map removed from catalog.
3. **XP inflation confusion** — If server grants bonus XP, badge **“NETWORK BONUS”** so players distinguish sources.
4. **Daily reset surprise** — Surface **time until reset** in Daily protocols header when server time available; else local midnight with disclaimer.
5. **Web autoplay** — INTEL tab switch must not assume music started without gesture where required (`docs/SCREEN-MUSIC-SPEC.md` §6 / `rules/08` §12).

---

## 11. Implementation architecture (client)

### 11.1 Suggested layers

- **`IntelViewModel`**: consumes `ProgressionRepository`, `SessionRepository`, `DailyProtocolsRepository`, `NarrativeRepository` (bundled `intel_card`), optional `IntelRemoteDataSource`.
- **State:** `IntelUiState` as stable data class; loading/error for optional network legs only — **core** INTEL fields available synchronously from disk.

### 11.2 Persistence keys (illustrative)

`intel_progress:v1`, `intel_dailies:v1:{date_bucket}`, `intel_last_session:v1` — namespace under app DataStore / SQLDelight per `rules/13` spirit.

### 11.3 Parity

Same UI and behavior on Android, iOS, Desktop, Web (where shipped); platform differences only for **image loading** and **time zone** APIs.

---

## 12. Testing

| Test | Intent |
|------|--------|
| **Offline render** | Airplane mode: INTEL shows last snapshot, no crash |
| **PLAY NOW resolution** | Matrix: in-progress / last map / cold install |
| **Daily claim idempotency** | Double-tap claim → single XP increment |
| **Ranked round active** | INTEL does not show hidden truth; server strings sanitized |
| **Reduced motion** | Meters animate minimally; ping disabled |
| **Localization** | Long tier names truncate gracefully in XP chip row |

---

## 13. Roadmap — potential of INTEL (product design space)

These items are **not** v1 requirements; they capture **why** INTEL matters long-term.

1. **Intel card deck** — Horizontally scrolling **cards**: satellite snippets, “hard region” warnings from analytics patterns (`docs/GAME-ENGINE.md` §5.1 heatmap idea), mission teasers.
2. **Seasonal ladder** — Time-limited tiers with reset cosmetics; still separate from **ranked** verified boards.
3. **Streak and habit** — Consecutive days with ≥1 guess; optional **non-punishing** streak freeze item (monetization ethics TBD).
4. **Faction chronicle** — Role-flavored **lore entries** unlocked by cumulative accuracy (presentation only).
5. **Operator feed** — Read-only **changelog** / “patch notes” card from server JSON.
6. **Intel vs PRO split** — INTEL stays **lightweight telemetry**; heavy EO chat remains **PRO** to preserve cognitive split.
7. **Cross-device progression** — Account-linked XP bar (requires auth ADR); still no proof of non-ranked skill without ranked.

---

## 14. Related documents

| Document | Role |
|----------|------|
| `rules/01-navigation-architecture.md` | Route IDs, default tab SCAN, depth |
| `rules/07-screens-checklist.md` | Checklist row 4 (dashboard / INTEL) |
| `docs/NARRATIVE-AND-PROMPTS.md` | `intel_card`, daily flavor, visit pipeline |
| `docs/GAME-ENGINE.md` | Scoring inputs, round phases, AI vs golden |
| `docs/SCREEN-MUSIC-SPEC.md` | `music_intel` |
| `docs/CLIENT-SETTINGS-SPEC.md` | Audio prefs |
| `docs/RANKED-MODE.md` | Trust boundaries |
| `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` | Optional EO intel cards |
| `docs/NU_TONIC_ARTIFACT_REFERENCE.md` | Visual binding |
| `docs/INTEL-SCORING-AND-PROGRESSION-SPEC.md` | INTEL metrics as **copy + presentation** of client data and ranked server snippets |
| `stitch/dashboard/code.html` | Layout reference (legacy bottom bar labels **not** normative) |

---

| Version | Date | Notes |
|---------|------|-------|
| 0.5 | 2026-04-12 | **§10** footgun: “push/realtime” → **push/stream** wording (`docs/GAME-ENGINE.md` §14) |
| 0.4 | 2026-04-12 | **Solo-first copy:** §2.1 / §2.3 / §10 — no S2 / optional-match framing; INTEL session card + footguns aligned **`docs/GAME-ENGINE.md` §14** (**REST + local state**; no live-session implication) |
| 0.3 | 2026-04-12 | **§4.1** ranked INTEL: cosmetic timer + catalog in-flight; **verified** stats after **`submit`**; de-emphasize “pre-resolve secrets” framing |
| 0.2 | 2026-04-12 | Cross-link **`docs/INTEL-SCORING-AND-PROGRESSION-SPEC.md`** for progression and mock bindings |
| 0.1 | 2026-04-12 | Initial INTEL tab specification: layout, metrics, trust, networking, roadmap |

*End of document.*
