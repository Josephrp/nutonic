# Per-map leaderboards, map selection, POI submission, and score sync

This document records **product and engineering implications** of:

- Leaderboards reachable from the **SCAN** hub (map / level selection and related segments) and from the **RANK** tab — not only post-round results (`rules/01-navigation-architecture.md`).
- Leaderboard rows **scoped per map** (or per **level** if `level_id` is a finer grain than `map_id`—contract must define the key).
- **Explicit “Update”** control: reload **local** per-`map_id` rows and, if configured, refetch **optional** server aggregates (in addition to pull-to-refresh or enter-hook). **Auto-refetch / background polling is off by default** (`rules/05-networking-leaderboard.md`).
- **Hydration and local commit** of **golden** reference scores, **AI-vs-truth** rows, and related manifests **with** clients (server is source for published reference rows; clients cache and display).
- Clients may **submit a POI** (point of interest): **device location** on mobile where permitted, or **user-chosen** coordinates from the map UI.
- **Non-ranked default:** scores and rank history live in **device-local** storage per **`map_id`**—**no** score **`POST`** to the server is required (`rules/05-networking-leaderboard.md`, `rules/13-client-cache-and-data-plane.md`). **Optional** community sync may expose **sanitized, transport-secured** **`POST`** self-reports; server **stores and aggregates** only for that opt-in path. **Store builds:** **JWT + official-client allowlist + schema-strict bodies** for any **server-mutating** writes—see **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`**. **Ranked missions:** **guess-only** submit, **server** score truth—see **`docs/RANKED-MODE.md`**.

Normative rules live in **`rules/05-networking-leaderboard.md`**, **`rules/13-client-cache-and-data-plane.md`**, **`rules/01-navigation-architecture.md`**, and **`rules/07-screens-checklist.md`**.

---

## 1. Implications summary

| Topic | Implication |
|--------|-------------|
| **Navigation** | The **`Rank` / RANK** route must accept an optional **`map_id` (and optional `level_id`)** so the same composable serves **global** (“pick a map”) and **map-scoped** views. **SCAN** hub map/level selection must expose per-map leaderboard in **≤1 extra interaction** without violating **max depth** (`rules/01-navigation-architecture.md`)—prefer **switch to RANK with `map_id`**, **tab + route args**, or a **modal/sheet** reusing the same composable. **Final results** must deep-link **RANK** with the round’s **`map_id`**. Mission + map + leaderboard + play entry stay **converged in SCAN** where product default applies (`docs/SOCIAL-AND-COMPETITION.md`). |
| **API contract** | **Local** boards key rows by **`map_id`** (and optional **`level_id`**). Any **optional** community **`GET`/`POST`** carries **`map_id`**. OpenAPI must version fields (`ruleset_version`, `engine_version`) when server paths exist. |
| **Caching** | **Local** leaderboard rows: **per `map_id`** keys in disk/DataStore; **commit** after each round. **Optional** `GET` payloads: **commit** with **ETag** / **`content_version`** (`rules/13-client-cache-and-data-plane.md`). |
| **“Update” button** | **Client-initiated**: reload **local** rows; if community/reference `GET`s exist, refetch those. Show **loading / error / last-updated** when network paths are used (**no auto-polling by default**). |
| **Golden + AI rows** | May be **reference data** from server (Jobs/bundles) or computed **on device** after a non-ranked round resolves. Clients **must not** invent golden truth for remote maps; they **may** display bundled golden/AI metrics for **offline** maps. **Optional** community **`POST`** must not mutate golden reference unless an explicit **ops** path exists. |
| **POI submission** | Separate use case from **in-round guess** unless product explicitly merges them. **`POST`** bodies follow **OpenAPI** (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`). |
| **Score submission** | **Default:** persist to **local** store only—no network. For **optional** community **`POST`**: schema + **idempotency keys** per OpenAPI. **Optional** **`POST .../guesses/record`**: per-guess **telemetry** (coords + client distance)—**not** authoritative for non-ranked math (`docs/GAME-ENGINE.md` §12.3, `rules/05-networking-leaderboard.md`). |
| **Peer reveal** | **Map** control to show another player’s guess marker; **non-ranked** = cosmetic / social (hints do not affect it). **Ranked** = **forfeit** via server **`forfeit-reveal`** (`docs/RANKED-MODE.md` §4). |
| **Parity** | Desktop/web may lack GPS: **manual map pick** or typed coordinates must remain **first-class** alongside mobile “use current location” (`rules/00-product-intent.md`). |
| **Ops / Gradio** | Per-map tables in **`/ops`** must read the **same store** as player-facing **`GET /api/.../leaderboard`** (`rules/12-python-gradio-terramind-server.md`). |

---

## 2. Suggested API shape (illustrative)

Implementations should replace with real OpenAPI under the reference server.

| Method | Path | Role |
|--------|------|------|
| `GET` | `/api/maps` | List selectable maps/levels (`map_id`, title, thumbnail ref). |
| `GET` | `/api/maps/{map_id}/leaderboard` | **Optional** when product ships community boards: aggregated rows for **matchup dimensions** + optional **AI vs golden** summary. Query: `matchup`, `role`, `cursor`, `limit`. |
| `GET` | `/api/maps/{map_id}/reference` | Optional bundle: golden coordinates per `round_id`/`location_id` **metadata for display only**, precomputed **AI guess** rows, `content_version`, ETag. |
| `POST` | `/api/maps/{map_id}/scores/self-report` | **Optional** community sync only: sanitized payload + **idempotency-key**; **store** may require JWT. **Not** used for default non-ranked local play. |
| `POST` | `/api/maps/{map_id}/guesses/record` | **Optional** non-ranked: record **guess_lat/lon** + **client_distance_km** + ids for **telemetry / ops**; **no** cryptographic honesty claim. |
| `POST` | `/api/ranked/rounds/{round_id}/forfeit-reveal` | **Optional** ranked: peer-reveal **forfeit**; invalidates **`round_ticket`** (`docs/RANKED-MODE.md`). |
| `POST` | `/api/ranked/rounds/start` | **Ranked:** returns `round_id`, **`round_ticket`**, clue manifest **without** ground truth (`docs/RANKED-MODE.md`). |
| `POST` | `/api/ranked/rounds/{round_id}/submit` | **Ranked:** `guess_lat`/`guess_lon` + ticket; server returns **verified** score row. |
| `GET` | `/api/maps/{map_id}/leaderboard/ranked` | Optional path: ranked-only aggregates (or `?tier=ranked`). |
| `POST` | `/api/maps/{map_id}/poi` | User- or device-sourced POI proposal (see §3); **game server** validates and publishes for **map/hint/ranked** use **once accepted** (`docs/RANKED-MODE.md` §4). |

---

## 3. POI submission semantics

- **Purpose (typical):** suggest a **future round location**, flag an error on a map, or enrich community content—**define in product** and document in OpenAPI.
- **Sharing:** server returns a stable **`poi_id`** (or registers client-supplied id) so clients can build **share URLs** / deep links into the map hub (`docs/SOCIAL-AND-COMPETITION.md`).
- **Payload:** at minimum `lat`, `lon` (rounded server-side), optional `label` (sanitized string), optional `source`: `device_gps` | `map_pick` | `manual_entry`.
- **Mobile:** request **runtime location permission**; never send location without user action confirming submit.
- **Server:** validate range, rate-limit per **client/session id**, store **audit fields** (timestamp, IP hash if policy allows)—**no secrets** in client.

---

## 4. Client hydration and “commit”

1. **Load** **local** leaderboard for `map_id` (always). **Fetch** `GET .../reference` or optional community **`GET .../leaderboard`** only when product configures those URLs.
2. **Validate** `content_version` / schema before merging into **local map bundle store**.
3. **Commit:** write atomically to app storage so the next session shows **last good** snapshot; on conflict (older ETag), prefer **newer server** row or **merge** policy documented in client.
4. After each round, **commit** the **local** leaderboard for that `map_id`. After **optional** **`POST` score**, either **invalidate** per-map **community** cache or **apply** returned snippet per OpenAPI.

---

## 5. UX checklist

- [ ] From **SCAN** hub **map/level selection**, user can open **leaderboard for that map** without hunting **RANK** (global pick-map flow still lives on **RANK** when no `map_id` is selected).
- [ ] **“Update”** reloads **local** data and any **optional** `GET`s; shows **spinner + error + retry** for network legs (**no auto-polling by default**).
- [ ] **Per-map** empty state (“No uplinks for this sector yet”) vs global empty state.
- [ ] POI flow: **preview pin** + confirm submit; accessibility labels for screen readers.

---

## 6. Related documents

| Document | Role |
|----------|------|
| [`rules/05-networking-leaderboard.md`](../rules/05-networking-leaderboard.md) | Normative API + per-map + POI rules |
| [`rules/13-client-cache-and-data-plane.md`](../rules/13-client-cache-and-data-plane.md) | Cache keys, hydration commit |
| [`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md) | **SCAN** / **RANK** tabs, default shell tab, map selection → leaderboard access without deep stacks |
| [`docs/GAME-ENGINE.md`](GAME-ENGINE.md) | §13 scoring + API sketch alignment |
| [`docs/SOCIAL-AND-COMPETITION.md`](SOCIAL-AND-COMPETITION.md) | Async competition by `map_id`, POI share, no lobbies |
| [`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`](POI-PACKAGES-AND-OFFICIAL-CLIENTS.md) | POI tree, server bundles, optional local inference, JWT / official-app |
| [`docs/RANKED-MODE.md`](RANKED-MODE.md) | Ranked mission APIs, tickets, verification layering |

---

*Non-ranked leaderboards default to **local-only** (no score POST). Optional community `GET`/`POST` and ranked paths remain documented for products that enable them.*

| Version | Date | Notes |
|---------|------|--------|
| 0.1 | 2026-04-07 | Initial: per-map boards, POI, hydration |
| 0.2 | 2026-04-07 | **Non-ranked default = local-only** leaderboards; optional community `GET`/`POST`; ranked unchanged |
| 0.3 | 2026-04-12 | Optional **`guesses/record`**, ranked **`forfeit-reveal`**, peer-reveal implications |
