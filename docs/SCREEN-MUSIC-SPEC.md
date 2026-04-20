# NU:TONIC — Screen music specification

This document defines **background music (BGM)** shipped with the app: **one loop per primary screen / shell surface**, **mandatory music on/off control in the header (or equivalent top chrome) on every shipped screen**, and how that ties to [`CLIENT-SETTINGS-SPEC.md`](CLIENT-SETTINGS-SPEC.md), [`docs/DESIGN.md`](DESIGN.md), and [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md).

**Audience:** client engineers (Compose `commonMain` + audio expect/actual), sound design, build/CI owners (asset size), UX.

---

## 1. Goals

- **Thematic continuity:** Each major surface has its own **identified** loop so the world feels consistent with the Neon Relic HUD (`docs/DESIGN.md`) without a single generic track.
- **User agency:** Players can silence music **without opening SETUP**, from **every** screen that ships in production builds.
- **Parity:** Android, iOS, Desktop, and Web (where shipped) use the **same** route → track mapping and the **same** toggle semantics.
- **Separation from SFX:** Music is **not** UI click sounds or map feedback; those use `audio.sfx_volume` (SETUP).

---

## 2. Non-goals

- **Streaming** from the internet (no CDN music in v1); all loops are **bundled** under version control with the client.
- **Dynamic procedural score** that replaces the per-screen loop table (optional future product).
- **Per-screen remembered mute** (e.g. “mute only on gameplay”) — v1 uses a **global** music master; see §5.

---

## 3. Route → track mapping (canonical)

Each row is **one** primary music asset (seamlessly loopable, normalized loudness). **Stable `track_id`** is used in code and CI; filenames may match `track_id` for clarity.

| `track_id` | When it plays | Stitch / product reference |
|------------|----------------|----------------------------|
| `music_splash` | Splash / cold start before shell | `refs/stitch/splash_screen/` |
| `music_auth` | Authentication / reconnect surface | `refs/stitch/authentication/` |
| `music_role` | Role selection (Human / Astronaut / Alien) | `refs/stitch/role_selection/` |
| `music_scan_hub` | **SCAN** tab: map list, mission pick, pre-game hub | Primary content of SCAN (`rules/01-navigation-architecture.md`) |
| `music_gameplay` | World map round (active guess window) | `refs/stitch/world_map_gameplay/` |
| `music_success` | Post-guess success overlay | `refs/stitch/success_overlay/` |
| `music_results` | Final results / tactical breakdown | `refs/stitch/final_results/` |
| `music_intel` | **INTEL** tab (dashboard) | `refs/stitch/dashboard/` |
| `music_rank` | **RANK** tab (leaderboard surfaces) | `refs/stitch/final_results/` “Global ranks” family |
| `music_setup` | **SETUP** tab (protocol configuration) | `refs/stitch/settings_protocol/` |
| `music_pro` | **PRO** tab (VLM tools shell) | `refs/VLMExample/` port (`rules/06-server-vlm-tim-and-on-device-ml.md`) |

**Rules**

- **Navigation:** On route change, **crossfade** (recommended 400–800 ms) from the previous loop to the new one when `audio.music_master_enabled` is true and `audio.music_volume` is greater than zero.
- **Overlays:** Success overlay **replaces** `music_gameplay` with `music_success` while visible; dismissing restores gameplay or results track per navigation graph.
- **Same stitch family:** INTEL and standalone dashboard mocks share **`music_intel`** unless product later splits variants—document in revision table if so.

---

## 4. Asset pipeline

- **Location (recommended):** `nutonic/shared/src/commonMain/composeResources/files/music/<track_id>.<ext>` (or repo-agreed path under `shared` resources). **Do not** reference `https://` audio in production.
- **Repository status (2026-04-20):** The KMP tree ships **eleven** minimal **PCM `.wav`** files (one per **`track_id`** in §3) as **silence placeholders** so `PlatformBgmPlayer` can open decoders in dev/CI; **replace** with mastered, licensed loops and normalize loudness per §4 **Loudness** before store release.
- **Format:** Prefer **Ogg Vorbis** or **AAC** depending on platform decoder support in your chosen KMP audio stack; keep **one** master format in `commonMain` if the player API allows, otherwise document per-target transcodes in `rules/03-kotlin-multiplatform-structure.md`.
- **Loudness:** Target consistent LUFS across tracks so SETUP’s `audio.music_volume` slider feels predictable.
- **Licensing:** Only ship tracks with **cleared** commercial use; record credits in `NOTICE.md` if required.

---

## 5. Music on/off control (every screen)

### 5.1 Placement

- **Every shipped screen** in [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md) (including **main-shell tabs** and **full-screen flows** before the shell) exposes a **single-tap** control in the **top app bar** (stitch header zone: logo left, profile right — control sits in the **trailing cluster**, e.g. beside profile, or trailing edge if profile hidden).
- **Iconography:** “Music on” vs “music off” states (e.g. `volume_up` / `music_off` equivalent) from the **single bundled icon set** (`docs/NU_TONIC_ARTIFACT_REFERENCE.md`).
- **Accessibility:** `contentDescription` must reflect state (“Mute music” / “Unmute music”); **48dp** minimum touch target.

### 5.2 Behavior (global master)

- The header control toggles **`audio.music_master_enabled`** (boolean, persisted) defined in [`CLIENT-SETTINGS-SPEC.md`](CLIENT-SETTINGS-SPEC.md) §6.7.
- When **off**: stop or fade out the current loop within ~200 ms; **do not** auto-resume until the user toggles on or enables music in SETUP.
- When **on**: resume the **current route’s** track respecting `audio.music_volume` and `audio.mute_when_backgrounded`.
- **SETUP** shows the same persisted state: header toggle and Audio section must **stay in sync** (one DataStore / preference source).

### 5.3 Relationship to SETUP sliders

- `audio.music_volume` — scales BGM when master is on.
- `audio.sfx_volume` — independent; header music toggle **does not** mute SFX unless product later adds a combined “mute all audio” (not default).
- `audio.mute_when_backgrounded` — OS-appropriate pause when app backgrounded; independent of master, but when backgrounded + mute rule fires, do not flip `audio.music_master_enabled`.

---

## 6. Implementation notes (KMP)

- Own a small **`ScreenMusicController`** in `commonMain` (route + lifecycle + prefs); **platform actual** for decoder/output (Media3 / AVAudioPlayer / JVM clip / web AudioContext) per [`rules/03-kotlin-multiplatform-structure.md`](../rules/03-kotlin-multiplatform-structure.md).
- **Web:** autoplay policies may block audio until first user gesture — **first tap** on Initialize / any header control may need to **prime** the audio graph; document in UX copy if required.
- **Reduced motion** does not imply mute music; only visual motion is affected (`CLIENT-SETTINGS-SPEC.md` §4.1).

---

## 7. Related documents

| Document | Relevance |
|----------|-----------|
| [`CLIENT-SETTINGS-SPEC.md`](CLIENT-SETTINGS-SPEC.md) §6.7 | Preference keys, SETUP grouping |
| [`docs/DESIGN.md`](DESIGN.md) §5 | Header chrome + music control styling |
| [`rules/02-design-system.md`](../rules/02-design-system.md) | Component parity |
| [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md) | Per-screen “must include” |
| [`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md) | When `track_id` switches with tabs |
| [`rules/08-ux-and-performance-footguns.md`](../rules/08-ux-and-performance-footguns.md) | Audio latency / feedback |
| [`docs/NU_TONIC_ARTIFACT_REFERENCE.md`](NU_TONIC_ARTIFACT_REFERENCE.md) | Bundled assets rule |

---

## 8. Revision history

| Date | Change |
|------|--------|
| 2026-04-08 | Initial screen music spec: one loop per surface, global header toggle, SETUP linkage. |
