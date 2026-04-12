# NU:TONIC — Narrative content, lore, and generated game elements

This document specifies **story**, **diegetic framing**, **build-time prompts**, and **optional runtime copy** (LLM / cache). **In-round play** centers on the **cached Mapbox still** as the **primary** geographic reference; **optional labeled assists** (Street View description packs, three-tier useful hints) ship from the same bundle pipeline and are **not** authorial narrative (`docs/GAME-ENGINE.md` §9–§11). It aligns with **`rules/00-product-intent.md`**, **`rules/06-server-vlm-tim-and-on-device-ml.md`**, **`rules/07-screens-checklist.md`**, **`docs/GAME-ENGINE.md`**, and **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`**.

---

## 1. Goals

1. **Narrative-first framing** — Short, readable **text boxes** during **mission selection**, **map / level selection**, **on-map briefing**, **success / results**, and **INTEL** so the game feels mission-driven without heavy UI.
2. **No “repeat rounds” grind** — Prefer **cached** or **stable** bodies; long prose is not re-shown every attempt unless the player opens “full brief.”
3. **Deterministic builds** — **Authorial** bundles: same git revision → same serialized **`PromptBundle`** (reproducible QA). **Generated** rows are additionally keyed by **`content_version`** / cache keys (`rules/13-client-cache-and-data-plane.md`).
4. **Offline-friendly** — Runtime reads **embedded** authorial JSON by default; **server- or job-hydrated** narrative may layer on with **timeouts and fallbacks** (`rules/06-server-vlm-tim-and-on-device-ml.md`).

---

## 2. Lore frame (canonical)

These statements are **fiction for tone and copy**; they do not add hidden game mechanics.

| Element | Canon |
|--------|--------|
| **Premise** | After **sanctions** cut supply lines, **orbital crews**, **surface humans**, and **off-world “alien”** contacts are stranded or isolated—but **still cooperating** to **reconstruct Earth** from fragments of memory, imagery, and signals. |
| **Cooperation** | Everyone is on the same side of **remembering real places**; competition is **who recalls best** (scores, leaderboards), not faction war in the default shell. |
| **Roles (Human / Astronaut / Alien)** | **Identity and tagging only.** They have **no bearing on game math**: same scoring rules, same clue pipeline, same ranked verification for a given mission (`rules/05-networking-leaderboard.md`, `docs/SOCIAL-AND-COMPETITION.md`). Roles may appear in **UI labels**, **leaderboard filters**, and **optional salutation in generated text**—never as undisclosed buffs or nerfs. |
| **Helpful AI entity** | A **benevolent in-universe intelligence** frames **mission copy** and **INTEL** flavor; **finding the place** on the map uses the **cached Mapbox still** as the **primary** reference, with **optional** **pre-cached** Street View prose and **useful-hint tiers** exposed as **separate assist** UI (`docs/GAME-ENGINE.md` §9). |

---

## 3. Content pipeline (scripts / Datasets → bundles)

**Diegetic story (SCAN):** Mission and briefing text can still use **Neon Relic** tone (`docs/DESIGN.md`); that copy is **not** an alternate source of geographic evidence for the round.

**Technical pattern (product intent):**

1. **Input** — Curated **`map_id` / `poi_id` / `mission_id`** rows in **`data/`** plus **scripts** and **Dataset** jobs that emit **catalog JSON**, **downsampled Mapbox stills**, and **`content_version`** slices for the client build.
2. **Primary still** — Each round references **one** Mapbox still path or URL—the **same** still in the reference layer (`docs/GAME-ENGINE.md` §9–§10).
3. **Assist bundles** — Optional **`streetview_hint_pack`** and **`useful_hints`** `{tier_1..tier_3}` materialized in CI; **separate** from **`prompts/`** narrative.
4. **Narrative** — Authorial **`prompts/`** blocks and optional **LLM**-generated mission chrome are **pre-baked** in CI; they do **not** embed assist strings—assists render from **dedicated** UI slots.
5. **Serve to clients** — **Bundled** or **manifest `GET`** keyed by **`content_version`**; optional HTTP refresh between releases.

**UI:** INTEL cards, SCAN briefing panels, and **optional** loading copy while bundle I/O resolves.

---

## 4. Generated content inventory (explicit)

Each row lists **what** is generated, **who runs inference**, **where prompts live**, and **typical cache key**.

| Artifact | Generator | Prompt / template owner | Cache / delivery | Notes |
|----------|-----------|-------------------------|------------------|--------|
| **Mission descriptions** | Server or job (LLM) | `prompts/llm/mission_description_system.md` (+ mission YAML vars) | `mission_id` + `content_version` on game API or Dataset manifest | **Requires a prompt** (system + user blocks). Feeds **mission_select** and **INTEL** hooks. |
| **Suggestions** (next actions, soft nudges, non-spoiler tips) | Server or job (LLM) | `prompts/llm/suggestions_system.md` | Per `map_id` / session policy | **Requires a prompt**; must be **schema-bounded** if any field is `POST`ed back (`rules/05-networking-leaderboard.md`). |
| **POI / sector narrative** (flavor only) | Optional LLM in CI | `prompts/llm/…` | `(poi_id \| map_id)` + `content_version` | **Does not** replace the **primary** Mapbox still; keep separate from **assist** slots. |
| **In-round primary reference** | **Script / Dataset** export | N/A | `map_id` / `round_id` + `content_version` | **Mapbox downscaled still** (`docs/GAME-ENGINE.md` §9). |
| **Street View description pack** (SCAN assist) | HF Jobs + **`inference/streetview_pano_service`** + **`inference/lfm_vl_hint_service`** (batch) | `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` | `round_id` + `content_version` | **Pre-cached prose** at sampled viewpoints; **ranked forfeit** if consumed before `submit` (`docs/RANKED-MODE.md`). |
| **Useful hints (3 tiers)** (SCAN assist) | Script / job (LLM or curated gazetteer) | `prompts/llm/…` or `data/` generators | `round_id` + `content_version` | **Tier 1–3** increasing specificity (continent → regional EO landmark / hydrology → country); **schema-capped**; **ranked forfeit** if revealed before `submit` unless OpenAPI narrows. |
| **PRO** coordinate dashboard | On-device VLM + server bundles | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` | Job / `bundle_id` | **Not** the SCAN loop. |
| **Success / debrief lines** | Optional LLM (short) | `prompts/llm/debrief_user.md` | `round_id` post-submit or local-only template | “Memory fragment recovered” tone; can merge **distance** from **client-known** post-submit facts. |
| **INTEL “daily protocols” flavor** | Mix: authorial MD + optional LLM one-liners | `prompts/missions/` + `prompts/llm/daily_protocol_flavor.md` | Mostly bundled; optional daily server slot | Keeps dailies fresh without huge UI. |
| **Error / resilience copy** | Authorial + tiny template vars | `prompts/shared/uplink_strings.md` | N/A | Maps HTTP failures to **in-universe** lines (`rules/05` § Errors). |
| **Sequence / mission IDs** (e.g. `#XJ-992-ALPHA`) | Deterministic generator or server | `prompts/shared/sequence_id_pattern.yaml` | Optional per round | Cosmetic **telemetry** tone on results screens. |

---

## 5. Source layout: `prompts/` (extended)

**Convention:** repo root or `nutonic/` root—**one** canonical path in Gradle; structure:

```
prompts/
  index.md                        # style guide, tone, banned phrases
  missions/
    <mission_id>.md               # authorial sector intros
  maps/
    <map_id>.md                   # optional per-map authorial stubs
  shared/
    strings.md                    # reusable authorial snippets
  llm/
    mission_description_system.md
    suggestions_system.md
    debrief_user.md
    daily_protocol_flavor.md
  vlm/
    visit_poi_system.md           # optional ops / PRO-adjacent (not SCAN location clue)
```

**Markdown + YAML front matter** for authorial files (see **§ 7**). **LLM prompt** files may be plain text with **`{{variable}}`** placeholders; CI should **lint** for unresolved placeholders.

---

## 6. Build-time serialization (authorial only)

**Rule:** A **Gradle task** walks `prompts/missions/**`, `prompts/maps/**`, `prompts/shared/**` (not necessarily every `llm/` / `vlm/` file—those may ship as raw assets for the server only):

1. Parse YAML front matter; normalize body for Compose.
2. Emit **`generated/.../PromptBundle.json`** with `content_hash`.
3. **CI:** duplicate `id`, unknown `slot`, invalid `roles` array.

**Runtime:** Load bundle from **Compose resources**; filter by `slot`, `map_id`, `mission_id`. **Do not** block map gestures on I/O (`rules/08-ux-and-performance-footguns.md`).

---

## 7. Slots (`slot`) — where text appears

| `slot` | Typical UI |
|--------|------------|
| `mission_select` | Mission picker: title + short paragraphs |
| `map_select` | Map grid blurb |
| `map_overlay` | On-map glass panel / first-open tooltip |
| `success_overlay` | Post-guess emotional beat (authorial or cached LLM) |
| `intel_card` | INTEL tab: memory stability, protocols |
| `results_debrief` | Final results: tactical copy beside scores |

Implementers expose **`NarrativeBlock(slot, context)`** plus a parallel **`GeneratedAssistChannel`** for VLM/LLM streams (`rules/06-server-vlm-tim-and-on-device-ml.md`).

**Front matter `roles`:** If present, filters **which authorial block** shows—**flavor only**; same slots can exist for all three roles with different prose **without** changing mechanics.

---

## 8. Relationship to AI “help” (VLM and TerraMind TiM)

| Layer | Role |
|-------|------|
| **Authorial `PromptBundle`** | Stable, QA’d, no ML. |
| **Server LLM / VLM** | Mission text, suggestions, **visit** narratives; **cached**; keys in OpenAPI or manifest. |
| **On-device VLM** | **Hints** and **PRO** tab experiments; **allowlisted** context; never block core loop. |
| **Server TerraMind TiM** | **EO / multimodal** clues and structured outputs per TerraTorch **`tim_modalities`**; **not** raw tensors in UI—may inform **which** cached narrative or clue variant to attach. Clients consume **HTTP only** (`rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`). |

**Labeling in UI:** Distinguish **“Operator brief”** (authorial), **“Signal assist”** (server generated), **“Local inference”** (on-device), so players understand **why** wording may change between offline and online.

---

## 9. Additional narrative and generative opportunities

Use this as a backlog for **tone** and **systems**; each item should trace to **prompt file**, **API field**, or **static string**.

| Opportunity | Idea | Generation |
|-------------|------|------------|
| **Splash / boot** | Subtitle “Memory is all that remains,” build string, sector id | Mostly authorial; **footer stats** may hydrate from manifest |
| **Authentication screen** | “Reconnect to Earth,” system access version | Authorial + **config** version string |
| **Role selection** | Three cards: same stakes, different **voice** (“stable Earth knowledge” vs “orbital memory” vs “xeno lens”) | Authorial per role **only**—no stat tables |
| **SCAN hub** | “Scan point” labels, fake grid IDs | Template + `map_id` hash suffix |
| **Timer / signal expiration** | “Signal degradation imminent” one-liners | Authorial pool or **LLM** with **hard length cap** |
| **Post-round leaderboard titles** | “Cartographer,” “Signal Ghost” | Authorial tiers or **server** assigns from score bands |
| **SQUAD / async flavor** | “Others remembered this sector” without lobbies | **Optional** `GET` snippets when community APIs exist (`docs/SOCIAL-AND-COMPETITION.md`) |
| **SETUP copy** | Neural adaptation, encryption active | Mostly authorial; **“Upload config”** success may echo server |
| **Loading / skeleton** | Rotating **lore** tips | Authorial list; no ML required |
| **PRO tab** | In-world excuse for advanced VLM tools | Authorial frame around **`refs/VLMExample/`** port (`rules/01`) |
| **HTTP errors** | Themed refusals (“**UPLINK INTERRUPTED**”, etc.) | Authorial templates mapping to HTTP **4xx** / retries |

---

## 10. Testing

- **Snapshot tests** on `PromptBundle.json` from a golden `prompts/` fixture.
- **Contract tests** for any **OpenAPI** field that carries generated strings (max length, HTML stripped).
- **Red-team prompts** (ranked): ensure **no** golden coordinates in client-controlled fields logged or echoed.

---

## 11. Related documents

| Document | Role |
|----------|------|
| `docs/GAME-ENGINE.md` | Round flow, map modal, assist pipeline |
| `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` | Orchestrator vs workers, cache-only hot paths |
| `docs/SOCIAL-AND-COMPETITION.md` | Async competition, roles on leaderboard rows |
| `rules/05-networking-leaderboard.md` | Sanitized POST bodies, errors |
| `rules/06-server-vlm-tim-and-on-device-ml.md` | SCAN **bundled** assist UX, **PRO** on-device rules, ranked constraints |
| `rules/07-screens-checklist.md` | Where narrative appears |
| `docs/INTEL-TAB-SPEC.md` | **INTEL** tab: `intel_card`, metrics copy, daily protocols, optional server intel |
| `docs/INTEL-SCORING-AND-PROGRESSION-SPEC.md` | **INTEL** progression: client metrics + ranked server snippets as **presentation only**; `intel_card` band keys |
| `rules/13-client-cache-and-data-plane.md` | `ETag`, `content_version`, offline |

---

| Version | Date | Notes |
|---------|------|--------|
| 0.3 | 2026-04-12 | **Beam the AI** diegetic frame; **§3** `data/` + batch bundling; **§4** hints row = pre-cached SCAN, PRO = on-device |
| 0.2 | 2026-04-07 | Lore frame, visit pipeline, generated inventory, opportunities, role-agnostic mechanics; align with `rules/06-server-vlm-tim-and-on-device-ml.md` |
| 0.1 | 2026-04-07 | Initial: `prompts/` layout, build serialization, slots, separation from AI assist |

*End of document.*
