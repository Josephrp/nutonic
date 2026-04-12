# Networking and leaderboard

## Rule: contract-first API

- Maintain a **documented contract** (OpenAPI, JSON schema, or shared `docs/api.md`) co-located with the reference server implementation.
- Kotlin models in **`commonMain`** must match the contract; breaking changes bump version or use explicit API versioning in paths.

## Trust: ranked vs non-ranked (document in OpenAPI)

**Product rule:** Deployment trust follows whether the **mission is ranked**, plus **store** packaging rules for writes.

| Mission | Auth on write (typical) | Score truth |
|--------|------------------------|-------------|
| **Non-ranked** | **No score POST required:** leaderboards are **device-local** by default (`rules/13-client-cache-and-data-plane.md`). **Optional** community / sync features may expose **score POST** under OpenAPI—then **reference / lab:** weak session; **store builds:** **JWT** + **registered official client** for those writes + **POI POST** where gated (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` §4). | **Client-held** round truth; **non-ranked leaderboard rows** live in **local store** (per `map_id`); server has **no** copy unless the player (or product) uses an **optional** submit path. |
| **Ranked** | **JWT + official client** + **`round_ticket`** (or equivalent) on **start** / **submit** | **Server-verified:** ground truth is **server-held**; client sends **guess coordinates only** (+ ticket/metadata); server **recomputes** distance/score (`docs/RANKED-MODE.md`). |

For **ranked** missions, **do not** accept `distance_km` / `points` from the client as authoritative—**ignore** or **reject** those fields on ranked submit paths; only **server-computed** values feed ranked aggregates.

## Ranked missions — server-held POIs and verified submits

- **Intent:** A **ranked** (or **pro**) tier uses **server-secret** round definitions: the client receives **clue assets** (e.g. downsampled stills, bounds, narrative handles) per OpenAPI but **not** pre-round WGS84 truth for that `round_id`.
- **Start round:** `POST` (or equivalent) returns `round_id`, short-lived **`round_ticket`**, clue manifest—**HTTPS + JWT + official client**; optional **Play Integrity / App Attest** on start when product requires. **No** server-returned **play time budget** or **submit deadline**; client uses **local catalog** for HUD (`docs/RANKED-MODE.md` §4).
- **Submit:** Client sends **`guess_lat` / `guess_lon`** (+ `round_ticket`, `Idempotency-Key`); **no** unbounded text; optional **structured** fields only as schema allows. Server validates ticket, recomputes **haversine** (or product score) vs **server-stored** truth, writes **verified** leaderboard row.
- **User POI:** `POST .../poi` is **schema-strict** and processed **only** on the **game server**. **Initial product:** once the server **accepts** a POI, it is **immediately** available for **map selection hydration**, **SCAN** hint/manifest rows, and **ranked** round selection for other players—**no** separate client-declared `ranked_eligible` flag. Optional **moderation queues** may be added later in OpenAPI without changing this default intent.
- **Separation:** Expose **ranked** leaderboards separately from **non-ranked local** views and any **optional** community aggregates (query param or path) unless product explicitly merges with clear UI labels.
- **Full design:** **`docs/RANKED-MODE.md`**.

## Leaderboard model: non-ranked local (default) vs optional community POST vs ranked

### Non-ranked — **local leaderboards (product default)**

- **Non-ranked leaderboards do not require any server submission.** After each round, the client **appends or merges** rows into **per-`map_id` local storage** (see `rules/13-client-cache-and-data-plane.md`): scores, roles, matchup facets, **AI vs golden** metrics from that session, timestamps, and optional display handle for “YOU” labeling.
- **Parity:** the same **dimensions** and **UI composables** (`Leaderboard dimensions` below) apply to **local rows**—filters and tabs operate on **device history**, not on a remote aggregate.
- **Do not** hardcode rows in production UI as if they were global facts. **Seeded / demo** data is allowed only behind **`BuildFlavor` / compile flag / debug menu** clearly named `MockApi`.
- **No trust claim:** local boards are **personal (per device)**; they are not proof of global rank unless combined with **ranked** or a **documented optional** community API.

### Optional — community self-report (OpenAPI only when product ships it)

- If product adds **opt-in** or **community** sync, **`POST`** (or batch) **self-report** payloads may include: **display handle**, **player role** (`HUMAN` | `ASTRONAUT` | `ALIEN`), **opponent role** / **matchup type**, **score / precision**, optional **`round_id`**, **`ruleset_version`**, timestamps—**all** schema-defined. Server **stores and aggregates** for that feature only; it still **does not** prove non-ranked math against client-held truth.
- **`GET`** community leaderboard responses (when present): **filtering and presentation** only—not mathematical proof for non-ranked rows.

### Optional — non-ranked guess recording (telemetry / ghosts)

- Separate from **community self-report** (aggregates) when product wants a **per-guess audit trail**: e.g. **`POST /api/maps/{map_id}/guesses/record`** with **`guess_lat` / `guess_lon`**, **`client_distance_km`** (or points), **`ruleset_version`**, **`location_id`** / `round_instance_id`, **`Idempotency-Key`**, optional **JWT** / session subject.
- **Trust:** Server rows are **non-authoritative** for non-ranked scoring; **`commonMain`** + **local** leaderboard remain the source of truth (`docs/GAME-ENGINE.md` §0, §12.3). Use for **ops**, **replay**, or **optional peer-marker** sources when `GET` contracts expose redacted pins.
- **Rate-limit** and **schema-clamp** like other writes; **reject** bodies that claim ranked verification.

### Peer reveal (another player’s marker) and SCAN ranked assists

- **Map UI** exposes an explicit control (e.g. **Reveal uplink**) to show **another player’s guess** as a **distinct** marker from **self** and **AI**—an **optional hint**, not a lobby or requirement that other players submit (`docs/GAME-ENGINE.md` §10.1).
- **Non-ranked:** Reveal and **Street View / useful-hint** assists are **optional** and **do not** change local score math. **SCAN** narrative, assist panels, and overlay usage are **orthogonal** to lock-in guess rules per **`docs/GAME-ENGINE.md` §9–§11**.
- **Ranked:** **Any** of the following **before** successful **`submit`** **forfeits** verified ranked participation for that `round_id` (no verified row, or **DNF** per OpenAPI): **peer reveal**, **opening the Street View description pack**, or **revealing any useful-hint tier** (three-tier pre-cached EO/geography hints—default product: **all tiers** count unless OpenAPI defines a ranked-safe subset). Client **must** call documented server endpoints so forfeits are **server-attested**—e.g. **`POST /api/ranked/rounds/{round_id}/forfeit-reveal`** and **`POST /api/ranked/rounds/{round_id}/forfeit-assists`** (illustrative); OpenAPI may **merge** into one **`.../forfeit-ranked-integrity`** with a **`reason`** enum. **Do not** rely on client-only flags. After forfeit, **`round_ticket`** is invalid for **`submit`**.

### Ranked

- Unchanged: **server-verified** rows per **`docs/RANKED-MODE.md`**.

## Per-map scope (required)

- **All leaderboard views (local or server)** are keyed by **`map_id`** (and optionally **`level_id`**). Local stores use the same keys (`leaderboard:local:{map_id}` or equivalent). OpenAPI must define **`map_id`** for any **optional** `GET`/`POST` community paths; **no** ambiguous “global only” production UI if play is **per-map**.
- **Optional** **`GET` leaderboard** / **`POST` self-report scores** (when shipped) must include **`map_id`** in the path or validated query—**same** `map_id` as the round or selection screen.
- **Golden** reference metrics, **precomputed AI-vs-truth** rows, and other **read-only reference payloads** for a map may still be served under **`map_id`** (optional `GET`; see `docs/LEADERBOARD-MAP-POI-SCORES.md`). Clients may also compute **AI vs golden** purely from **local round** data without any `GET`.

## Map / level selection → leaderboard (required entry)

- The **map or level selection** surface (primary **SCAN** hub — `rules/01-navigation-architecture.md`) **must** expose the **per-map leaderboard** in **at most one extra deliberate action** (e.g. row trailing action “Ranks”, toolbar icon, or inline preview + “see all”).
- Reuse the **same** leaderboard composable as the **RANK** tab, driven by **navigation state** `{ map_id, optional level_id }`. Avoid maintaining two divergent UIs.
- **Explicit “Update”** control: for **local** boards, **Update** reloads from **local store** (and may re-run merge/sort). If the product wires **optional** server `GET`s (community board or reference bundle), **Update** / pull-to-refresh triggers the **same** refetch as on-enter for those resources. **Auto-refetch / auto-polling is off by default**. When network `GET`s exist, clients **should** show **last-fetched** time or **`content_version`** when useful.

## POI submission (optional product feature)

- Clients may **`POST` a POI** for a map: **coordinates** plus optional **label**, with **`source`** ∈ `device_gps` | `map_pick` | `manual_entry` | product-defined enums only.
- **New POI** flows that used **on-device inference** must still **POST structured fields** (e.g. suggested `lat`/`lon`, `confidence`, `model_id`); **never** accept a single unbounded “description” field as the only payload (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` §3–4).
- **Sharing (social):** responses should expose a stable **`poi_id`** (or registered client id) so users can **share** a POI with others via **deep link** or OS share sheet (`map_id` + `poi_id` opens the **map hub** at the right context—`docs/SOCIAL-AND-COMPETITION.md`). Sharing is **not** the same as submitting an **in-round guess** unless product explicitly merges flows.
- **Mobile:** use platform location APIs **only** after permission and **explicit user confirm**; never silent upload.
- **Sanitization (server):** clamp lat/lon to WGS84, **round** precision (e.g. 5–6 decimal places max stored), reject NaN/inf, cap string lengths, strip control characters.
- **Abuse:** rate-limit per session / IP; optional moderation queue for POIs shown publicly—document behavior in OpenAPI.

## Score submission: sanitized and transport-secured (**optional** community + ranked only)

- **Non-ranked default:** no network score submission—skip this section for core local play.
- **Sanitize:** validate **OpenAPI / JSON Schema**, numeric ranges for scores and distances, enum roles, max lengths on **display handle** and any text fields; **reject unknown properties**; reject HTML and control characters.
- **Transport security:** **HTTPS only** in production; no secrets in query strings.
- **Replay / spam:** on **optional** **`POST` self-report** paths, require **`Idempotency-Key`** (or body field); server dedupes; **rate limit** per `map_id` + **subject** (JWT `sub` or session).
- **Optional hardening:** short-lived **`submit_nonce`** from `GET` preflight reduces blind replay; does **not** prove score correctness (`docs/GAME-ENGINE.md` §0).
- **Store-gated and ranked writes:** require **`Authorization: Bearer <JWT>`** issued by the reference server when OpenAPI marks the path as authenticated; JWT claims must bind **`app_id`**, **`platform`**, **`build`** (and optional **`user`**). Reject tokens from **unregistered** signing certificates or wrong bundle ids. **Do not** accept **ranked** **start/submit** or **store** score/POI writes on “open” POST endpoints without authentication when enabled.
- **Ranked submit:** require valid **`round_ticket`** (or successor) matching `round_id` and subject; **reject** bodies that include **client-authoritative** score fields as the source of truth—server overwrites or ignores per OpenAPI.

## Official client program (store builds + ranked writes)

- **Register** each shipping binary: Android **package name + SHA-256 of signing cert** (or Play App Signing flow), iOS **bundle id + Team ID +** optional **App Attest** enrollment, desktop **API key + device-bound refresh** (weaker—document limits).
- **Issue JWTs** from **FastAPI** (not Gradio): client credentials or user login → access token (short TTL) + optional refresh; validate in dependencies on every **optional** **`POST /api/.../scores`** (community self-report), **`POST /api/.../poi`**, and **`.../ranked/rounds/start`** / **`.../submit`** paths that mutate state when OpenAPI requires auth.
- **Payload contract:** only fields defined in OpenAPI—**no** arbitrary long strings, **no** nested JSON blobs for “metadata” unless schema-approved. POI labels and messages use **hard caps** (e.g. ≤ 200 chars) and **enum**-constrained `source`.
- **Platform attestation:** when available (**Play Integrity**, **DeviceCheck / App Attest**), pass **attestation evidence** as a **dedicated optional field** validated server-side; failures → **403** with telemetry, not silent accept for **ranked** **start/submit** when product requires attestation (document minimum OS / Play Services requirements).
- **Sideload / unofficial builds:** either **blocked** from authenticated store endpoints or routed to **sandbox leaderboard**—document behavior.

## Leaderboard dimensions (required semantics)

The **RANK** tab, **final_results** “Global ranks” area, **SCAN** hub per-map slice, and **per-map** leaderboard views must make these **comparable views** available where the product shows tabs (tabs, sections, or query params—match OpenAPI):

1. **Human vs Human** — entries where both sides are **Human** role (or filter `matchup=human_human`).
2. **Human vs Alien** — PvP or comparative rows where roles are **Human** and **Alien** (`human_alien`).
3. **Human vs Astronaut** — **Human** and **Astronaut** (`human_astronaut`).
4. **Alien vs Astronaut** — **Alien** and **Astronaut** when applicable (`alien_astronaut`).
5. **AI vs golden answer** — a **separate track** (or dedicated columns) showing how the **in-round AI marker** performed vs the round’s **ground truth** (distance km / derived score). This is **not** the same as human PvP ranks; UI should label it clearly (e.g. “SYNTHETIC / VS TRUTH”).

**Role filters** (Human / Astronaut / Alien) on stitch-style tabs still apply for **narrowing** lists, but must remain **consistent** with the matchup dimensions above.

**Cross-player async competition (server-visible):** Requires **ranked** missions and/or an **optional** community **`POST`/`GET`** contract—see **`docs/SOCIAL-AND-COMPETITION.md`**. **Default non-ranked:** each device keeps its own **per-`map_id`** history; **Human / Astronaut / Alien** still **tag local rows** for filters and matchup views.

## Hydration, golden / AI reference data, and UX

- **RANK** tab, **SCAN** hub per-map slice, and results **ranks** sections: **on enter**, load **local** `map_id` leaderboard from disk first (always available for non-ranked). **Optional** `GET`s (reference bundle, community board) follow the same **fetch on enter** + **Update** / pull-to-refresh pattern when configured. **Auto-refetch after load is off by default** (`rules/13-client-cache-and-data-plane.md`).
- **Final results → RANK (required):** After a round, navigation **must** open **RANK** with the **same `map_id`** (route argument, saved state handle, or query — document one pattern). Data shown is **local** by default; optional server sections are additive.
- **Golden / AI-vs-truth:** may come from **`GET .../reference`**, embedded optional `GET` leaderboard payload, or **entirely from the resolved local round** (no network). When `GET` is used, **merge** into per-map cache and **commit** with **`ETag` / `content_version`** per `rules/13`. Clients **do not** overwrite server golden reference via score `POST`; **ops** APIs aside, **optional** community **`POST`** is the only client-originated server row for non-ranked.
- After **optional** **`POST` self-report**, refresh server-backed slices only via **user action** or **inline response snippet**—**not** automatic background refetch by default.
- **Offline / server down:** **local** boards still work; optional server sections show **last-known** cached `GET` data when product allows (`rules/13-client-cache-and-data-plane.md`).

## Auth and identity

- **Game server session (preferred):** Clients obtain and send **`Authorization: Bearer <token>`** (device/session JWT issued by the game server—**not** necessarily a user account) for **API calls** that hydrate maps, leaderboards, manifests, and **expensive** cached paths. This **reduces spam** and lets the server **cache** Street View / VLM-backed work behind authenticated subjects. **No** mandatory **social** sign-in; tokens may be anonymous device-bound (`rules/00-product-intent.md`).
- **Default shell:** **No** mandatory **account** sign-in to use **SCAN**, **INTEL**, **RANK** (read/browse), **SETUP**, or **PRO** — aligned with `rules/01-navigation-architecture.md`. **Ranked** **start/submit**, **store-gated writes**, and **PRO jobs** still use the **same** or stricter token rules per OpenAPI.
- **Non-ranked, reference builds:** Players are **not** required to register a **user account**. Use **server-issued** session identity and/or **client-generated** display identifiers; duplicate handles are acceptable (document behavior).
- **Store builds:** **JWT required** for **write** paths that mutate **server-held** score aggregates, **published** POI catalogs, or other store-gated resources **when those paths exist** per OpenAPI (**optional** community submit, **POI**, etc.). **Pure local** non-ranked leaderboards **do not** use JWT. **User accounts** optional—JWT may represent **device-bound official client** without PII.
- **Ranked missions:** **JWT required** for **`ranked/rounds/start`** and **`submit`** (and any path that writes **verified** ranked rows); combine with **`round_ticket`** per **`docs/RANKED-MODE.md`**.
- **Leaderboard row “YOU”:** Open deployments — **local session id** / last submit token. Store or account flows — prefer **stable `sub`** from JWT or hashed device id **issued by server** (document privacy policy).
- **Implementation:** FastAPI issues and validates JWT; Gradio `/ops` does not replace this (`rules/12-python-gradio-terramind-server.md`).

## Errors

- Map network failures to **in-universe copy** where appropriate (“UPLINK INTERRUPTED”) but keep **technical logs** for developers (non-user-facing).

## Reference server

- The app may target a **reference implementation server** in-repo or sibling repo; base URL via config (debug default, release from config). **No** Hub tokens, **`hf` CLI**, or **server/ML service secrets** in clients (`rules/13-client-cache-and-data-plane.md`).

## Ops UI vs game API

- If the Python stack exposes **Gradio** for operators (e.g. read-only leaderboard table), it must be **mounted under FastAPI** on a **non-game path** (e.g. `/ops`). **Game clients** use **OpenAPI-documented REST** (`/api/...`), not Gradio queue endpoints, unless explicitly documented as an exception.
- Leaderboard data shown in Gradio and in JSON APIs must come from the **same store/service** to avoid drift. See **`12-python-gradio-terramind-server.md`**.
