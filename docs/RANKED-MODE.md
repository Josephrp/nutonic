# NU:TONIC — Ranked mode (server-held POIs, verified scores)

**Vocabulary:** **Ranked** here is **server-verified competitive SCAN** (also **Mode C** in `rules/05-networking-leaderboard.md`). It is **not** the **PRO** shell tab—the **PRO** tab is the **non-game** coordinate dashboard (`rules/01-navigation-architecture.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). Do **not** gate ranked play on **`POST .../pro/jobs`**, mix **`round_ticket`** state with **PRO** job IDs, or label ranked UI as “Pro mode.”

This document defines **product and engineering intent** for **ranked** missions that sit **alongside** default **reference / casual** play (`docs/GAME-ENGINE.md` §0, `rules/00-product-intent.md`). Normative API rules remain in **`rules/05-networking-leaderboard.md`**; POI packaging in **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`**.

> **Former path:** `docs/RANKED-AND-PRO-MODE.md` was renamed to avoid conflating **ranked** verification with the **PRO** tab. Update bookmarks and links to **`docs/RANKED-MODE.md`**.

---

## 1. Why this mode exists

| Problem in casual / **local-only** non-ranked (optional community aside) | Ranked response |
|----------------------------------|------------------------|
| Client holds **ground truth** in bundle or manifest → modified clients can **fabricate** scores. | **Server holds** ground truth for the active round until **resolve**; client receives **clue assets and metadata only** per contract. |
| **POST** body includes self-reported `score_km` / points → server cannot prove arithmetic honesty. | Client submits **`guess_lat` / `guess_lon`** (and minimal signed fields); server **recomputes** distance/score with the **same haversine** policy as `docs/GAME-ENGINE.md` / server reference. |
| Self-serve clients send malformed payloads. | **Mode B** controls plus **round-scoped tokens** (see §4); **Mode C** requires them for **writes** to ranked aggregates. |

---

## 2. Mode summary (align with `rules/05`)

| Aspect | Casual / reference (A) | Store integrity (B) | **Ranked (Mode C)** |
|--------|-------------------------|---------------------|----------------------|
| **Ground truth on device** | Yes (bundle/manifest) | Often yes | **No** for active ranked round |
| **Score source** | Client math → **local persist** (default); **optional** community **`POST`** if shipped | Same + JWT / official app on **server** writes | **Server-only** after `submit` |
| **Leaderboard row** | **Device-local** history (default); **optional** remote aggregate | Schema + identity gates on writes | **Verified row** tied to `round_id` / `session_id` |
| **User POI** | Optional propose → **game server** | Same + Mode B | **`POST .../poi`** only; once **accepted**, server publishes for **maps**, **hints**, and **ranked** selection—**no** client-only catalog path |
| **Typical JWT** | Optional | Required on writes | **Required** on ranked **start**, **submit**, **user POI** |

---

## 3. Lightweight client in ranked play

- **Ship static assets** as today: downsampled Mapbox (or equivalent) stills, redacted `poi.json` fields, `content_version`—but for **ranked** rounds the **server** chooses **`poi_id` / `round_id`** and may ship a **clue-only** manifest (no `lat`/`lon` truth in the bundle for that round).
- **On-device inference** for the **PRO tab only** (`rules/06-server-vlm-tim-and-on-device-ml.md`); **not** required for ranked **SCAN** clues (**cached Mapbox still** per `docs/GAME-ENGINE.md` §9).
- **Cached data:** clients may cache **completed** ranked results (server-returned score, rank delta) for UX. For an **in-flight** round, show **verified** distance/points only after a successful **`submit`** response—earlier UI should rely on **catalog labels** and cosmetic session copy, not provisional score fields.

---

## 4. Contract shape (illustrative — replace with OpenAPI)

Implementers should document real paths, errors, and TTLs. **Normative prefix for the game server:** **`/api/v1/...`** (e.g. `POST /api/v1/ranked/rounds/start`). Paths below omit the prefix for readability where they show `.../api/ranked/...` — **prefix with `v1`** in shipped OpenAPI (`plans/2026-04-07-complete-implementation-architecture.md` §4.1).

1. **`POST /api/ranked/rounds/start`** (or `.../sessions/start`)  
   - Headers: `Authorization: Bearer <JWT>`.  
   - Body: `map_id`, `ruleset_version`, optional product fields (e.g. ladder id)—**do not** overload **`pro`** or **PRO** naming for ranked; use **`tier=ranked`** or OpenAPI-defined enums if a leaderboard slice query needs a tier.  
   - Response: `round_id`, **`round_ticket`** (opaque, short-lived), **clue manifest** (imagery URLs, bounds, **no** ground truth), optional **server_viewport** for progressive-zoom products. **No server-side play time budget:** the server does **not** return **`play_budget_ms`**, **`submit_deadline`**, or any duration used to **accept or reject** submits. **Client play timer** (**`elapsed_play_ms`** / **`play_budget_ms`**) is **cosmetic only**—HUD and INTEL/session copy; it **must not** end **`PLAY`**, block submit, or trigger any fail state (`docs/GAME-ENGINE.md` §7.3).

2. **`POST /api/ranked/rounds/{round_id}/submit`**  
   - Headers: `Authorization`, `Idempotency-Key`, body includes **`round_ticket`**, **`guess_lat`**, **`guess_lon`**, optional **`client_reported_ms`** (or equivalent)—**accepted without verification**; may be **persisted** for analytics, ops, or **INTEL** copy; **never** used to accept/reject **`submit`**, adjust **verified** distance/points, or imply anti-cheat.  
   - Server: validate **`round_ticket`** and idempotency only—**not** any client-reported duration; load **secret** truth; compute **distance_km** / **points**; persist **verified** row; return **final** payload for UI.

3. **`POST /api/ranked/rounds/{round_id}/forfeit-reveal`** (optional but **required** if UI offers peer reveal in ranked)  
   - Invoked when the player explicitly **reveals another participant’s guess** before **`submit`**.  
   - Server: invalidate **`round_ticket`** (or mark round **DNF/forfeit**), persist audit row, return **409** / domain error on subsequent **`submit`** for the same `round_id`. **No** verified ranked score row for that attempt.  
   - **Rationale:** Peer reveal is incompatible with **guess-only** ranked integrity for that session; treat as **voluntary exit** from verified placement.

4. **`POST /api/ranked/rounds/{round_id}/forfeit-assists`** (optional but **required** if UI offers **Street View description** and/or **useful-hint** tiers in ranked)  
   - Invoked when the player **confirms** they want ranked-forbidden **SCAN assists**—i.e. **pre-cached AI Street View descriptions** and/or **one or more useful-hint tiers** (three-level progressive specificity: e.g. continent → regional EO landmark / hydrology → country), per **`docs/GAME-ENGINE.md` §9**.  
   - Server: **same** outcome as **`forfeit-reveal`**—invalidate **`round_ticket`**, **DNF/forfeit**, no verified row. OpenAPI may instead expose a **single** **`.../forfeit-ranked-integrity`** endpoint with `{ "reason": "peer_reveal" | "assists" | ... }`.  
   - **Rationale:** These assists narrow the search space beyond the **primary Mapbox still + map submit** contract; ranked verified rows remain **guess-only** from that baseline.

5. **`GET /api/v1/maps/{map_id}/leaderboard`**  
   - Query: `tier=ranked` or separate path **`/api/v1/maps/{map_id}/leaderboard/ranked`** so casual and ranked aggregates **do not mix** unless product explicitly merges with labels.

6. **`POST /api/v1/maps/{map_id}/poi`** (user POI)  
   - Same schema-strict rules as casual. The **game server** validates, stores, dedupes, and republishes the POI for **map lists**, **bundle refresh** (clue stills), and **ranked** round pools for other players **once accepted**—never trust client flag `ranked_eligible: true`.

---

## 5. API hygiene (ranked)

- **Schema validation** on request bodies (`rules/05`).
- **JWT** on ranked **start** / **submit** and **`round_ticket`** on submit (`rules/05`).
- **Server-verified score** for ranked rows (guess-only submit).

---

## 6. UX and parity

- **Clear mode switch** in UI: “Practice / Casual” vs **“Ranked”** so players understand **eligibility** (e.g. account or region gates when product defines them).
- **Same** `commonMain` navigation and map abstraction (`rules/04`); **different** data sources and submit handlers for ranked vs casual—avoid forking **routes** per platform.
- **Peer reveal in ranked:** If the product ships **Reveal uplink**, show a **destructive** confirmation (“Forfeit ranked uplink”) before calling **`forfeit-reveal`**. If the endpoint is **not** implemented, **hide** peer reveal in ranked play.
- **SCAN assists in ranked:** If the product ships **Street View descriptions** or **useful-hint** panels, show the same class of **destructive** confirmation (“Forfeit ranked assists”) before expanding content, then call **`forfeit-assists`** (or merged integrity endpoint). If not implemented, **hide** assist UI in ranked play.
- **Failure:** network fail mid-round → themed **“Uplink”** error; **do not** silently downgrade to **non-ranked / local-only** for the same `round_id`. Use **retry** or documented **server cancel**. **Cosmetic elapsed timer** may **pause** while backgrounded per **`docs/GAME-ENGINE.md` §7.3**—**not** an implicit mode switch and **not** a gameplay gate.

---

## 7. Related documents

| Document | Role |
|----------|------|
| `rules/05-networking-leaderboard.md` | Mode A/B/**C**, JWT, POI, ranked submit |
| `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` | POI tree, redacted bundles, threat model |
| `docs/LEADERBOARD-MAP-POI-SCORES.md` | Per-map APIs, hydration |
| `docs/GAME-ENGINE.md` | Default client authority vs ranked exception |
| `docs/SOCIAL-AND-COMPETITION.md` | Async competition; ranked as optional tier |
| `rules/13-client-cache-and-data-plane.md` | What may be cached before/after resolve |

---

| Version | Date | Notes |
|---------|------|--------|
| 0.1 | 2026-04-07 | Initial: server-held POIs, verified scores, user POI path, layering |
| 0.2 | 2026-04-07 | Casual column aligned with **local-default** non-ranked leaderboards (`rules/05`) |
| 0.3 | 2026-04-12 | §6 failure: no silent downgrade, no **forfeit** wording (timer details superseded by **0.5**) |
| 0.4 | 2026-04-12 | Client **count-up** timer + **`play_budget_ms`**; **POI** via server **immediate** ranked eligibility; on-device = **PRO tab** only cross-links |
| 0.5 | 2026-04-12 | **§4** ranked **start**: no server play budget; **submit**: no deadline validation |
| 0.7 | 2026-04-12 | **SCAN** clue = cached Mapbox still; trim attestation / anti-abuse prose; **§5** renamed API hygiene |
| 0.8 | 2026-04-12 | **§4** optional **`forfeit-reveal`**; ranked peer reveal **forfeits** verified row; **§6** UX warning |
| 0.9 | 2026-04-12 | **§4** optional **`forfeit-assists`** (Street View text + three-tier useful hints); **§6** destructive confirm for ranked assists |
| 1.0 | 2026-04-12 | **§4** / **§6**: play timer **cosmetic only**—no **`PLAY`** exit or submit gating; **`client_reported_ms`** unverified, may persist; **§3** cache copy de-emphasizes “secrets” framing |
| 1.1 | 2026-04-12 | **Rename** to `RANKED-MODE.md`; remove **“Pro”** as ranked synonym; **§4** contract list renumbered; start body: no **`tier=pro`** example; **vocabulary** callout vs **PRO** tab |

*Version column is semantic order (0.1 … 1.1), not necessarily the order edits were committed in git.*

*End of document.*
