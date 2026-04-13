# NU:TONIC — Social competition (map-centric, no lobbies)

This document states how players **compete and discover each other** without requiring **real-time lobbies** or **matchmaking rooms**. Normative networking rules remain in **`rules/05-networking-leaderboard.md`**; navigation in **`rules/01-navigation-architecture.md`**.

**Shell (aligned with `01`):** After splash + role, the **default main tab is SCAN** (converged map selection, play entry, and per-map leaderboard slice). **RANK** holds **global** aggregates plus **pick `map_id`** → **Play** returns to **SCAN** with that map. **No** dedicated social tab.

---

## 1. Core idea: same map — local history by default, server-visible competition when enabled

- Every **published map** (stable **`map_id`**, optionally **`mission_id`**) is the **unit of play** and **local leaderboard scope**: each device keeps **its own** non-ranked runs, scores, and role-tagged rows for that map (`rules/05-networking-leaderboard.md`). **No** score upload is required for default casual play.
- **Server-visible “same arena” competition** (seeing other players’ scores on a shared board) happens when the product enables **ranked** missions and/or an **optional** community **`GET`/`POST`** contract—see **`docs/RANKED-MODE.md`** and **`docs/LEADERBOARD-MAP-POI-SCORES.md`**. Until then, **async shared-map** leaderboards alone do **not** imply live opponents or a second-player transport (`docs/GAME-ENGINE.md` §14).
- **Optional peer guess on map:** **Reveal uplink** shows another marker as an **optional hint** (not a lobby or multi-player submit gate); **non-ranked** it is cosmetic; **ranked** it **forfeits** verified placement (**`docs/GAME-ENGINE.md` §12.4**, **`rules/05-networking-leaderboard.md`**). **Optional SCAN assists** (Street View descriptions, useful-hint tiers) follow the same **ranked forfeit** rule (**`docs/GAME-ENGINE.md` §9**).
- **Human / Astronaut / Alien** are **player-selected roles** used to **enrich** **local** (and optional server) leaderboard views—**not** separate queues or mandatory team matchmaking for reference play. **Lore and generated copy** for those roles are centralized in **`docs/NARRATIVE-AND-PROMPTS.md`**; **scoring and ranked rules stay role-agnostic** unless an ADR says otherwise.

---

## 2. Unified hub UI (no lobbies)

Product default: **mission selection**, **map selection**, **play on map**, and **per-map leaderboard** collapse into the **SCAN** hub (segments/sheets inside the **SCAN** tab — `rules/01-navigation-architecture.md`, `rules/07-screens-checklist.md`):

- Pick **mission** → pick **map** → read **narrative** → see **inline or one-tap leaderboard** for that `map_id` → **Play** / **Submit guess** without entering a **lobby** or **room code**.
- **No `LOBBY` state machine** is required for social competition (`rules/05-networking-leaderboard.md`: **auto-refetch off by default**; user pull-to-refresh / **Update**).

---

## 3. POI sharing as light social

- **`POST /api/v1/maps/{map_id}/poi`** (optional) can record user-suggested points; **sharing** a POI with others (system share sheet, deep link `nutonic://map/{map_id}?poi={poi_id}`, or HTTPS universal link) is **explicitly allowed** and helps discovery (“play this sector / check this marker”).
- POI share is **not** the in-round guess unless product merges flows; keep **guess submit** and **POI suggest** distinct in UI (`rules/05-networking-leaderboard.md`).
- **Store builds:** treat **POI + score writes** as **official-client-only** when enabled—**JWT**, **registered signing identity**, **strict JSON Schema**—see **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`**. **Ranked** missions add **round_ticket**, **guess-only** submit, **server-verified** scores, **server-secret** POIs for active rounds. **`POST .../poi`** on the **game server** is the **only** ingestion path; once **accepted**, user POIs join **map selection**, **hint hydration**, and **ranked** pools for others **immediately**, alongside **`data/`**-curated packages (`rules/00-product-intent.md`, `docs/RANKED-MODE.md` §4).

---

## 4. Roles vs “playing against each other”

| Concept | Meaning |
|---------|--------|
| **Competition** | Same **`map_id`**: **non-ranked** — client computes distance and **persists** to **local** leaderboard (**no** server score **`POST`** by default); **ranked** — client **POST**s guess only, server computes score (`docs/RANKED-MODE.md`). **Optional** community sync is separate and documented in OpenAPI. |
| **Roles** | **Human**, **Astronaut**, **Alien** tag each row for **filters** and **matchup dimensions** (e.g. Human vs Alien comparisons)—see `rules/05` §Leaderboard dimensions. |
| **Optional PvP semantics** | Rows may include **opponent role** when product defines a pairwise round; default async model treats the field as **flavor / analytics**, not proof of a live duel. |

---

## 5. Related documents

| Document | Role |
|----------|------|
| `plans/2026-04-07-complete-implementation-architecture.md` | Phasing: map-centric async flow |
| `docs/LEADERBOARD-MAP-POI-SCORES.md` | Per-map API, POI, hydration |
| `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` | POI asset layout, server bundles, official-app JWT |
| `docs/RANKED-MODE.md` | Server-secret rounds, verified scores, user POI promotion |
| `docs/GAME-ENGINE.md` | Domain model, **solo-first** rounds, **REST**-first player API (`§14`) |
| `rules/05-networking-leaderboard.md` | **Local** default, optional community REST, dimensions |

---

| Version | Date | Notes |
|---------|------|--------|
| 0.8 | 2026-04-12 | **Reveal uplink** peer marker: hints orthogonal (non-ranked); ranked **forfeit** (`docs/GAME-ENGINE.md` §10.1, `rules/05`) |
| 0.7 | 2026-04-12 | **POI** via game server → **immediate** map/hint/ranked eligibility; aligns with `rules/00`, `docs/RANKED-MODE.md` §4 |
| 0.6 | 2026-04-07 | **Non-ranked leaderboards default to device-local**; server-visible competition = ranked and/or optional community APIs (`rules/05`) |
| 0.5 | 2026-04-07 | Remove live-multiplayer extension; ranked vs non-ranked; hydration defaults (`rules/05`) |
| 0.4 | 2026-04-07 | Align prose with **`rules/01`**: **SCAN** default hub, **RANK** global + `map_id`, no social tab |
| 0.3 | 2026-04-07 | Ranked (Mode C), separate boards, user POI promotion |
| 0.2 | 2026-04-07 | Mode B / official-client pointer for store POI + score writes |
| 0.1 | 2026-04-07 | Initial: async map competition, no lobbies, roles enrich boards, POI share |

*End of document.*
