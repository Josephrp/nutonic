# Kotlin Multiplatform structure

## Module boundaries

- **`shared` (`commonMain`)**: Navigation shell, design system, screen composables, ViewModels/state holders, DTOs, API interfaces, use cases, and **pure logic**.
- **Platform source sets** (`androidMain`, `iosMain`, `jvm` desktop, `webMain` / `js` / `wasmJs`): Entry points, permissions, secure credential storage, **map view binding**, file I/O, and other expect/actual bridges.

## Rule: no duplicate business logic per platform

If it affects **rules of the game**, **leaderboard ordering**, or **embedding consumption**, it lives in **`commonMain`** (or server). Android/iOS/desktop may only wrap APIs.

## Compose UI placement

- **Screens** that are identical across targets: implement in `commonMain` with shared theme.
- Use **`@Composable expect/actual`** only when unavoidable (e.g. map, camera, biometric). Keep actuals **thin**.

## Dependencies

- **Networking**: Ktor client (or agreed alternative) configured per engine in platform source sets or via supported multiplatform engine.
- **Serialization**: `kotlinx.serialization` for all API models shared with the server contract.
- **Time**: `kotlinx-datetime` for anything cross-timezone; avoid `java.time` in `commonMain`.

## Naming and packages

- Migrate away from sample names (`imageviewer`, `example.imageviewer`) as features land; **new code** uses a single root package (e.g. `com.nutonic.*`) per team convention.
- **`rootProject.name`** and application IDs should eventually match product, not the template name.

## Testing

- **commonMain**: unit tests for scoring client-side previews, parsers, state reducers. Use `kotlin("test")` in **`commonTest`** (see `shared/src/commonTest/...`).
- **Platform**: minimal UI tests where CI allows; focus on map and auth integrations (e.g. **`desktopTest`** with Compose UI tests).
- **Commands / CI / VS Code:** See **`11-vscode-testing-linting-and-ci.md`** for `./gradlew test`, `quality`, and GitHub Actions jobs.
