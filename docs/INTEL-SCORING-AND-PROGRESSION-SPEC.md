# NU:TONIC — INTEL scoring and progression (copy + metric bindings)

**Status:** Normative for **what INTEL may show**, **where numbers come from**, and **how copy maps to metrics**. It does **not** define a second gameplay score or trust path.  
**Date:** 2026-04-12  
**Audience:** Compose implementers, narrative owners, OpenAPI authors.

**Authority:** Binds to `docs/INTEL-TAB-SPEC.md`, `docs/GAME-ENGINE.md` §0 / §13, `docs/RANKED-MODE.md`, `rules/00-product-intent.md`, `rules/05-networking-leaderboard.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/NARRATIVE-AND-PROMPTS.md`, `docs/DESIGN.md`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md`.

**Layout reference (visual only, not runtime HTML):** `stitch/dashboard/code.html` — legacy bottom bar labels **HOME / MAP / PLAY** are **not** normative; shell tabs follow `rules/01-navigation-architecture.md` (**INTEL** = this surface). When this spec cites “dashboard mock,” it means that file.

---

## 1. Product rule: INTEL has no separate “intel score”

- **INTEL does not compute or own competitive scoring.** Round **distance**, **points**, and **golden truth** for **non-ranked** play remain **`commonMain`** per `docs/GAME-ENGINE.md` §0. **Ranked** verified **distance / points** come **only** from the server **after** `submit` (`docs/RANKED-MODE.md`).
- **INTEL is a presentation layer:** numbers and labels are **formatted copy** bound to:
  - **Client-held aggregates** (XP ledger, rolling performance, session snapshot, daily protocol progress), and
  - **Server-returned ranked / ladder snippets** when OpenAPI provides them (show **verified** competitive numbers only after **`submit`** resolves; until then use **catalog + cosmetic** session lines—see §3.4, §4).
- **Roles (Human / Astronaut / Alien)** affect **salutation and `intel_card` selection** only (`rules/06`, `docs/NARRATIVE-AND-PROMPTS.md` §2).

---

## 2. Dashboard mock → INTEL region → data binding

Each row: **Mock region** (`stitch/dashboard/code.html`) → **Canonical INTEL region** (`docs/INTEL-TAB-SPEC.md` §3) → **Binding** → **Source of truth**.

| Mock (stitch) | INTEL region | Binding | Source |
|----------------|--------------|---------|--------|
| App bar “`1,250 XP`” chip | App bar XP chip | `xp_total` (integer) | **Client:** persisted progression ledger (`docs/INTEL-TAB-SPEC.md` §5.1). Optional badge **NETWORK BONUS** if server grants additive XP via documented path. |
| “`Rank Progress: Silver IV`” + “`75%`” + bar | Rank progress | `engagement_tier_label`, `engagement_tier_percent` | **Client:** derived from `xp_total` against a **product tier table** (§4). **Not** the same string as **ranked competitive tier** unless product explicitly maps them (§6). |
| “`PLAY NOW`” CTA | PLAY NOW | Navigation only | **Client:** resolve per `docs/INTEL-TAB-SPEC.md` §8.1. |
| “`Memory Stability`” + “`92% SAFE`” + meter + body copy | Memory stability | `memory_stability_0_100`, `memory_stability_band_key`, `memory_stability_subcopy` | **Client:** `memory_stability_0_100` from §5. `memory_stability_subcopy` from **`intel_card`** slot or static band table (§5). Optional server **flavor line** only (no numeric authority). |
| “`Current Session`” card (title, duration, zone, image, Resume) | Current session | `session_headline`, `session_subline`, `session_badge`, `session_hero_ref`, `session_phase` | **Client:** last in-progress or last finished round summary from engine / local store. **Ranked in-flight:** mission/map titles from **catalog** + optional **cosmetic** elapsed timer (`docs/GAME-ENGINE.md` §7.3)—**not** a score signal. **Ranked post-resolve:** **verified** distance/points from server (§4.1). |
| “`Daily Protocols`” + rows + XP rewards | Daily protocols | `protocol_id`, titles, `xp_reward`, progress, state | **Client:** protocol definitions bundled or local config; optional server rotation per `docs/INTEL-TAB-SPEC.md` §5.4 / §7. |

---

## 3. Progression stats (normative shapes)

All structs are **logical**; OpenAPI may rename fields. **Version** progression saves with `progression_version` (or `ruleset_version`) per `docs/INTEL-TAB-SPEC.md` §4.2.

### 3.1 `xp_total` (engagement XP)

- **Meaning:** Long-horizon **meta** counter for unlocks / tier bar on INTEL. **Not** proof of skill on global leaderboards (`rules/05`).
- **Grants (examples):** round finished (non-ranked or ranked), distance band bonus, daily claim, first visit to map — each event appends a ledger row:  
  `{ "idempotency_key", "source", "amount", "ts", "map_id?", "round_id?", "mission_id?", "mode": "non_ranked" | "ranked" }`.
- **Display:** Locale-formatted integer; app bar chip in mock = **Space Grotesk** / tabular figures per `docs/NU_TONIC_ARTIFACT_REFERENCE.md` §3.

### 3.2 Engagement tier (`engagement_tier_label`, `engagement_tier_percent`)

- **Purpose:** Diegetic **“Rank Progress: {Tier}`”** line in the mock is the **engagement ladder**, not RANK tab aggregates.
- **Inputs:** `xp_total` and a **bundled tier table** `Tiers[]`: each tier has `id`, `display_name` (e.g. `Silver IV`), `xp_floor`, `xp_ceil`.
- **Bar:**  
  `engagement_tier_percent = round( 100 * (xp_total - xp_floor) / max(1, xp_ceil - xp_floor) )` clamped **0–100**.  
  If product uses **non-linear** curves, document in tier table JSON — still **client-only** unless OpenAPI adds server-driven tier (then treat as **display override**, not score truth).

### 3.3 Memory stability (`memory_stability_0_100`)

**Default (non-ranked + local history):**

1. Take the last **`N`** completed rounds (`N = 10` default), each with `distance_km` (or score-normalized distance) and `map_id`.
2. For each round, compute **precision percentile** vs the player’s **own historical distribution** on that `map_id` (if fewer than **3** prior rounds on map, use global self-history).  
3. **Median** of those percentiles → `p_median` ∈ [0, 1].
4. Map to display:  
   `memory_stability_0_100 = round( 100 * smoothstep(p_median) )`  
   where `smoothstep` is a monotone curve (e.g. piecewise linear) so one catastrophic round does not drop the meter from 100 to 0 — product may ship constants in `progression_config.json`.

**Ranked rounds:** After resolve, **distance_km** from **server payload** may **replace** client distance for that round in the same rolling window **for INTEL display only** (still not a new trust path).

**Qualitative band (`memory_stability_band_key`):**

| `memory_stability_0_100` | Band key | Mock-style suffix |
|--------------------------|----------|-------------------|
| 80–100 | `stable` | `SAFE` |
| 55–79 | `nominal` | `NOMINAL` |
| 30–54 | `drift` | `DRIFT` |
| 0–29 | `critical` | `CRITICAL` |

**Primary line:** `{memory_stability_0_100}% {BAND_SUFFIX}` (e.g. `92% SAFE`) using **`tertiary`** token for the suffix per mock.

**Subcopy (`memory_stability_subcopy`):** Prefer **`prompts/`** → slot **`intel_card`** keyed by `memory_stability_band_key` + optional `role` (`docs/NARRATIVE-AND-PROMPTS.md`). Fallback one-liner examples (replace via content):  
- `stable`: “System integrity optimal. Quantum drift within acceptable parameters.”  
- `drift`: “Uplink variance elevated. Recommend focused sector runs.”

### 3.4 Current session card

| Field | Rule |
|-------|------|
| `session_headline` | Mission or map title from **catalog** / last round bundle — **no** WGS84 in copy unless product explicitly teaches coordinates. |
| `session_subline` | Non-ranked: “Last result: **{distance_km}** km · **{points}** pts” from **client resolution**. Ranked post-resolve: “Verified: **{server.distance_km}** km · **{server.points}** pts”. In-progress: optional **cosmetic** elapsed line from **`elapsed_play_ms`** / §7.3 (`docs/INTEL-TAB-SPEC.md` §3)—**not** verified and **not** a fail condition. |
| `session_badge` | Short zone label (e.g. `Zone 04-B`) from **`map_id`** slice or mission code — **cosmetic**. |
| `session_hero_ref` | Local asset URI or **allowlisted** CDN still / clue art the **same** surfaces may already show in SCAN for that mission—**hero imagery only**, not a second evidence channel. |

### 3.5 Daily protocols

- **Copy:** Title + subtitle are **authorial** (`prompts/` / bundled JSON). Mock examples (“Data Fragment Recovery”, “Velocity Mastery”) are **tone references**, not mechanics until wired to real `protocol_id` targets.
- **Progress:** `progress_current` / `progress_target` must map to **observable client counters** (e.g. “rounds played today”, “maps completed”) — document per protocol in bundle. **Do not** claim mechanics the engine does not track.
- **XP label (`+200 XP`):** Must equal the **`amount`** granted on **claim** into the same `xp_total` ledger (single source of truth).

---

## 4. Ranked mode on INTEL (server stats + copy)

### 4.1 Allowed after round resolve

From **server return payload** or small **GET summary** (OpenAPI — illustrative fields):

- `last_ranked_distance_km`, `last_ranked_points`, `last_ranked_tier_delta` (e.g. `+12 RP`), `last_ranked_tier_name` (competitive ladder name if product uses one).
- **Aggregate** snippets: global or per-`map_id` **ranked** percentile / rank index — **only** if served from **verified** rows (`rules/05`).

**Copy pattern:** “Last uplink (ranked): **{points}** pts · **{tier_delta}** · **{tier_name}**” — all strings **schema-bounded**.

### 4.2 Forbidden on INTEL

- Presenting **optional community POST** rows as **ranked-verified**.
- Mixing **engagement tier** label with **ranked tier** label **without** distinct typography / prefix (e.g. “Ladder: Gold II” vs “Clearance: Silver IV”).

### 4.3 Active ranked round

Show **session** state: e.g. “Ranked sector active — return to **SCAN** to submit.” **Cosmetic** timer copy is allowed (**§7.3**); do not show **verified** ranked distance/points until **`submit`** succeeds.

---

## 5. Copy and typography (mock alignment)

- **Section headers:** `text-[10px]` uppercase tracking ≈ `0.2em`, **Space Grotesk** — map to `NutonicTypography` label style (`docs/DESIGN.md`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md` §3).
- **XP chip:** Cyan emphasis; **tabular nums** for stability.
- **Memory meter:** Glass panel, **tertiary** success for “safe” readout; optional gradient end accent in mock (`#B266FF`) is **decorative** — keep within **`docs/DESIGN.md`** semantic roles or map to `primary`/`tertiary` blend with a11y check.
- **Daily row trailing XP:** **Tertiary** for completed; **primary-container** accent for in-progress (mock pattern).

---

## 6. Implementation checklist

- [ ] Single **`ProgressionLedger`** writer: all XP mutations go through idempotent append.  
- [ ] **`IntelPresentationModel`** maps raw metrics → strings; **no** duplicate XP math in composables.  
- [ ] **`engagement_tier_*`** never reads from RANK tab server payload unless field is explicitly tagged `engagement` in OpenAPI.  
- [ ] Ranked post-resolve: INTEL reads **last resolved** snapshot from secure session store; clears or masks on logout per product.  
- [ ] **`intel_card`** entries exist for each `memory_stability_band_key` × optional `role`.  
- [ ] Strings table in CI: no unresolved `{{vars}}` for shipped slots (`docs/NARRATIVE-AND-PROMPTS.md`).

---

## 7. Related documents

| Document | Role |
|----------|------|
| `docs/INTEL-TAB-SPEC.md` | Tab layout, navigation, audio, roadmap |
| `stitch/dashboard/code.html` | Visual density and mock strings |
| `docs/GAME-ENGINE.md` | Round scoring authority |
| `docs/RANKED-MODE.md` | Ranked trust |
| `docs/NARRATIVE-AND-PROMPTS.md` | `intel_card`, slots |
| `docs/LEADERBOARD-MAP-POI-SCORES.md` | RANK tab vs INTEL distinction |

---

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-12 | Initial: INTEL = copy + client metrics + ranked server snippets; mock bindings; memory stability bands; engagement vs ranked tier separation |
| 0.2 | 2026-04-12 | Aligned with **`docs/GAME-ENGINE.md` §7.3** (play timer cosmetic only) and **`docs/INTEL-TAB-SPEC.md` §4.1** (ranked INTEL: cosmetic timer + catalog in-flight); session card + **§4** de-emphasize “secret leak” framing; **§4.2** drop pre-resolve ground-truth bullet |

*End of document.*
