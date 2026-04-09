# Networking and leaderboard

## Rule: contract-first API

- Maintain a **documented contract** (OpenAPI, JSON schema, or shared `docs/api.md`) co-located with the reference server implementation.
- Kotlin models in **`commonMain`** must match the contract; breaking changes bump version or use explicit API versioning in paths.

## Leaderboard hydration

- **Do not** hardcode leaderboard rows in production code. Mock data is allowed only behind a **`BuildFlavor` / compile flag / debug menu** clearly named `MockApi`.
- **Leaderboard screen** (and embedded “Global ranks” on results): fetch on enter and on **pull-to-refresh** or explicit refresh; show loading, empty, and error states with retry (stylized per theme).
- Support **role filters** (Human / Astronaut / Alien) if the results UI specifies tabs; query params or path segments must match server.

## Auth and identity

- **Default:** **Light or no auth** for reference play—anonymous **`player_id`** / session cookie acceptable; document in OpenAPI.
- **When auth is required:** Issue **JWT access** (short-lived) and optional **refresh** tokens from the **Python reference server** (**FastAPI**—not Gradio alone). Validate JWT in FastAPI dependencies; **Gradio `/ops`** may reuse the same ASGI middleware or a separate ops secret.
- **Platform practice:** If JWT is enabled, clients store tokens in **secure storage** (Android Keystore-backed, iOS Keychain, desktop keychain or encrypted file—`rules/03`).
- **Guest mode** must remain explicit in API and UI when offered; leaderboard row **YOU** needs a **stable** server-issued id (anonymous or authenticated).

## Multiplayer (when enabled)

- **Match state** may use WebSockets or SSE in addition to REST; separate **Leaderboard** (eventually consistent) from **live match** (real-time) channels.
- Reconnection: resume or show “signal lost” themed state; do not silently drop scores.

## Errors

- Map network failures to **in-universe copy** where appropriate (“UPLINK INTERRUPTED”) but keep **technical logs** for developers (non-user-facing).

## Reference server

- The app targets a **reference implementation server** in-repo or sibling repo; base URL via config (debug default, release from secure config). **No** Hub tokens, **`hf` CLI**, or embedding **secrets** in clients (`rules/13-client-cache-and-data-plane.md`).

## Ops UI vs game API

- If the Python stack exposes **Gradio** for operators (e.g. read-only leaderboard dashboard), it must be **mounted under FastAPI** on a **non-game path** (e.g. `/ops`). **Game and TS clients** use **OpenAPI-documented REST** (`/api/...`), not Gradio queue endpoints, unless explicitly documented as an exception.
- Leaderboard data shown in Gradio and in JSON APIs must come from the **same store/service** to avoid drift. See **`12-python-gradio-terramind-server.md`**.
