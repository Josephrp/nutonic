# Hugging Face Space deploy (NU:TONIC)

The workflow **`.github/workflows/huggingface-deploy.yml`** runs **pytest**, then **`tools/hf_deploy/deploy_space.py`**, which:

1. Stages a Space tree (`pyproject.toml`, `src/`, Space `README.md` from `templates/`, plus either `Dockerfile` for Docker SDK profiles or `app.py` for Gradio SDK profiles).
2. Uses the **`hf`** CLI (from **`huggingface_hub>=1.10`**, entry point **`hf`**, not `huggingface-cli`):
   - `hf auth login --token …`
   - `hf repo create <repo> --repo-type space --space_sdk <space_sdk> --exist-ok`
   - `hf upload <repo> <stagedir> . --repo-type space --delete "*"` (full mirror commit)
3. Syncs **Space variables**, **secrets**, and **hardware** from **`tools/hf_deploy/profiles/<service>.yaml`** via **`HfApi`** (`add_space_variable`, `add_space_secret`, `request_space_hardware`). The Hub does not yet expose `hf spaces secret set`; add/update at runtime uses those APIs.
4. Runs a post-deploy smoke test via **`tools/live_inference_smoke.py`** and uploads a JSON artifact (`hf-smoke-*`) per job.

Install locally:

```bash
pip install -r tools/hf_deploy/requirements.txt
hf --version
python tools/hf_deploy/deploy_space.py --service lfm_vl_hint --repo-id YOUR_USER/your-space --dry-run
```

## GitHub repository secrets

| Secret | Purpose |
| -------- | --------- |
| `HF_TOKEN_TONIC` | Write token for **Tonic** Spaces (LFM hints, TerraMind). |
| `HF_TOKEN_NUTONIC` | Write token for **NuTonic** Spaces (game server, PRO materialization). |
| `HF_TOKEN` (optional fallback) | When `HF_TOKEN_TONIC` or `HF_TOKEN_NUTONIC` is unset, the workflow uses **`HF_TOKEN`** next, then **`HF_API_WRITE`**, for Hub upload auth. Same token is fine if it has **write** on the target Space repos. |
| `HF_API_WRITE` (optional fallback) | Used only when org-specific and `HF_TOKEN` deploy secrets are empty; must be a **write-capable** Hub token for the Spaces you deploy. |

### Troubleshooting: `Missing HF_TOKEN in environment` in Actions

The deploy step sets runner env **`HF_TOKEN`** from GitHub secrets. That variable is **empty** when **none** of the configured secrets for that job are defined.

1. In the repo: **Settings → Secrets and variables → Actions**, add **`HF_TOKEN_TONIC`** and **`HF_TOKEN_NUTONIC`** (recommended), **or** a single **`HF_TOKEN`** as in the table above.
2. Confirm the token can **`hf upload`** to the target Space (`Tonic/nutonic-lfm-vl-streetview`, `NuTonic/nutonic-game-server`, etc.).
3. Fork PRs do not receive secrets; deploy jobs are expected to fail or be skipped for untrusted forks unless you use a different policy.

Optional **runtime** secrets (see `profiles/*.yaml` — each maps a Hugging Face Space secret key to a **repository secret** whose value is exported under the **same name** as an env var in the deploy job):

| Env var on runner (from GitHub secret) | Used for |
| ---------------------------------------- | ---------- |
| `TONIC_GOOGLE_MAPS_API_KEY` | Optional Google Street View Static key for the Street View pano Space. Workflow fallback: `GOOGLE_MAPS_API_KEY`. |
| `TONIC_LFM_OPENAI_API_KEY` | LFM `openai_compatible` backend |
| `TONIC_LFM_OPENAI_BASE_URL` | Optional OpenAI-compatible base URL |
| `TONIC_LFM_SATELLITE_OPENAI_API_KEY` | Satellite caption `openai_compatible` backend |
| `TONIC_LFM_SATELLITE_OPENAI_BASE_URL` | Optional satellite caption OpenAI-compatible base URL |
| `TONIC_TERRAMIND_HF_TOKEN` | Optional Hub token inside TerraMind Space for model pulls |
| `NUTONIC_JWT_SECRET` | Game server Space secret `JWT_SECRET` |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL (often secret) |
| `NUTONIC_RANKED_DATABASE_URL` | Ranked store URL |
| `NUTONIC_MAPBOX_ACCESS_TOKEN` | PRO materialization → Space secret **`MAPBOX_ACCESS_TOKEN`**. If unset, the workflow uses **`MAPBOX_ACCESS_TOKEN`** (same token name the worker reads at runtime). |
| `NUTONIC_INFERENCE_HMAC_SECRET` | PRO worker inbound HMAC (Space secret **`NUTONIC_INFERENCE_HMAC_SECRET`**). **Required** while `profiles/pro_materialization.yaml` sets **`NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC: "1"`** — otherwise the Space fails startup (`RuntimeError` in lifespan). Generate a long random string and use the **same** value on the game server as **`NUTONIC_INFERENCE_HMAC_SECRET`** when it calls this worker. Alias in CI: **`INFERENCE_HMAC_SECRET`**. |

If an optional secret is **unset**, that key is skipped (no empty secret pushed).

### Production checklist (Spaces)

| Space / service | You likely already have | Add in GitHub Actions (if missing) | Pushed to Space as |
| ----------------- | ------------------------- | ------------------------------------- | --------------------- |
| **All deploy jobs** | `HF_TOKEN` and/or `HF_API_WRITE` | `HF_TOKEN_TONIC`, `HF_TOKEN_NUTONIC` for separate org tokens | *(auth only — not a Space env)* |
| **Street View pano** | `GOOGLE_MAPS_API_KEY` if using real Google imagery | `TONIC_GOOGLE_MAPS_API_KEY` optional; profile defaults to stub mode | `GOOGLE_MAPS_API_KEY` |
| **LFM-VL hints** | — | `TONIC_LFM_OPENAI_API_KEY` / `TONIC_LFM_OPENAI_BASE_URL` only if `LFM_VL_BACKEND=openai_compatible` (profile default is **transformers**) | `OPENAI_*` |
| **LFM-VL satellite** | — | `TONIC_LFM_SATELLITE_OPENAI_API_KEY` / `TONIC_LFM_SATELLITE_OPENAI_BASE_URL` only if `LFM_SATELLITE_BACKEND=openai_compatible` (profile default is **transformers**) | `OPENAI_*` |
| **TerraMind TiM** | `HF_API_READ` or `HF_TOKEN` | `TONIC_TERRAMIND_HF_TOKEN` for a dedicated read token (optional) | `HF_TOKEN` |
| **Game server** | — | **`NUTONIC_JWT_SECRET`**, **`NUTONIC_LEADERBOARD_DATABASE_URL`**, **`NUTONIC_RANKED_DATABASE_URL`** for real prod (Postgres URLs as needed) | `JWT_SECRET`, `NUTONIC_LEADERBOARD_DATABASE_URL`, `NUTONIC_RANKED_DATABASE_URL` |
| **PRO materialization** | `MAPBOX_ACCESS_TOKEN` | **`NUTONIC_INFERENCE_HMAC_SECRET`** (required with current profile) | `MAPBOX_ACCESS_TOKEN`, `NUTONIC_INFERENCE_HMAC_SECRET` |

Secrets such as **`GOOGLE_MAPS_API_KEY`**, **`NUTONIC_HYDRATION_OUTPUT_DATASET`**, and **`GITLEAKS_LICENSE`** are used by **other** jobs/scripts, not by **`huggingface-deploy.yml`**. Add them only where those workflows or tools read them.

**Redeploy everything from Actions:** use **Actions → huggingface — deploy Spaces → Run workflow**, target **all**, after secrets exist. Pushes to **`main`** on paths listed in the workflow also run deploys.

## Profiles

Edit **`tools/hf_deploy/profiles/<service>.yaml`** for production defaults:

- **`variables`**: public Space environment variables (non-secret).
- **`secrets`**: map **Space secret name** → **runner env var name** (CI must export the value).
- **`space_sdk`**: optional, defaults to `docker`. Use `gradio` for Hugging Face ZeroGPU services; ZeroGPU is Gradio-SDK only and requires an `app.py` plus decorated GPU functions.
- **`hf_space_owner_org`**: optional Hub namespace prefix for `--repo-id` (e.g. `Tonic`). When set, `deploy_space.py` exits with an error if `repo_id` is not exactly `"{org}/…"`. The three GPU / ZeroGPU profiles set **`Tonic`** so those Spaces cannot be deployed under **NuTonic** by mistake.
- **`space_hardware`**: passed to `request_space_hardware` (e.g. `zero-a10g`, `cpu-basic`). Requires an account that can request that flavor.
- **`sleep_time_seconds`**: optional; `-1` means do not sleep on upgraded hardware where supported.

## Default Space repos

| Service | Default `repo_id` |
| --------- | ------------------- |
| Street View pano | `Tonic/nutonic-streetview-pano` |
| LFM-VL hints | `Tonic/nutonic-lfm-vl-streetview` |
| LFM-VL satellite captions | `Tonic/nutonic-lfm-vl-satellite` |
| TerraMind TiM | `Tonic/nutonic-terramind-tim` |
| Game server | `NuTonic/nutonic-game-server` |
| PRO materialization | `NuTonic/nutonic-pro-materialization` |
