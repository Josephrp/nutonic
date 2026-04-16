# Kotlin Multiplatform structure



## Module boundaries



- **`shared` (`commonMain`)**: Navigation shell, design system, screen composables, ViewModels/state holders, DTOs, API interfaces, use cases, **game state machine, scoring, difficulty, levels, fairness rules** for **non-ranked** missions, **ranked round orchestration** (call start/submit, hold `round_ticket`, render server scores) for **ranked** missions, **PRO** surface (VLM port from **`refs/VLMExample/`**), and **pure logic**.

- **Platform source sets** (`androidMain`, `iosMain`, `jvm` desktop, `webMain` / `js`): Entry points, permissions, **map view binding**, file I/O, and other expect/actual bridges. **Secure credential storage** only if an optional account/JWT mode is added later—not required for **default local-only** non-ranked leaderboards.



## Rule: no duplicate business logic per platform



If it affects **rules of the game**, **local score/XP computation** (non-ranked), **local leaderboard row shape**, **payload shape** for **optional** community **`POST`** or **guess-only** ranked submits, **role modifiers**, or **AI-vs-golden metrics the client displays**, it lives in **`commonMain`**. Android/iOS/desktop may only wrap platform APIs (maps, storage). The reference server **optionally aggregates** community non-ranked submissions when that API exists and **computes** scores for **ranked** missions (`docs/RANKED-MODE.md`).



## Compose UI placement



- **Screens** that are identical across targets: implement in `commonMain` with shared theme.

- Use **`@Composable expect/actual`** only when unavoidable (e.g. map, optional biometrics). Keep actuals **thin**.



## Dependencies



- **Networking**: Ktor client (or agreed alternative) configured per engine in platform source sets or via supported multiplatform engine—used for **optional** leaderboard POST/GET and content/VLM calls, not for mandatory score validation.

- **Serialization**: `kotlinx.serialization` for all API models shared with the server contract (optional community score DTOs, ranked DTOs, optional hydration responses) and for **local** leaderboard persistence models in **`commonMain`**.

- **Time**: `kotlinx-datetime` for anything cross-timezone; avoid `java.time` in `commonMain`.



## Naming and packages



- **Identifiers:** ship under **`com.nutonic.*`**; do not reintroduce template names such as `imageviewer` / `example.imageviewer` in Kotlin, resources, or web bundle names.

- **`rootProject.name`** and application IDs should eventually match product, not the template name.



## Audio (screen music)

- **Routing and prefs** for which loop plays (`track_id`) and **`audio.music_master_enabled`** / volumes live in **`commonMain`** per [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md) and [`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md) §6.7.
- **Decoding and output** use **expect/actual** (or a supported KMP audio library) in platform source sets; keep actuals **thin** — start/stop/crossfade + volume apply only.



## Testing



- **commonMain**: unit tests for **scoring**, state reducers, parsers, and leaderboard DTO builders. Use `kotlin("test")` in **`commonTest`** (see `shared/src/commonTest/...`).

- **Platform**: minimal UI tests where CI allows; focus on **map** integrations (e.g. **`desktopTest`** with Compose UI tests). Optional auth flows are not the default test priority.

- **Commands / CI / VS Code / mandatory local verification:** See **`11-vscode-testing-linting-and-ci.md`** for `./gradlew test`, `quality`, GitHub Actions jobs, and **PM2 + `logs/`** assessment (**§9.2**) before merging **`nutonic/**`** changes.

