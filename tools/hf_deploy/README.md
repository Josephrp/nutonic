# Hugging Face Space deploy (NU:TONIC)

The workflow **`.github/workflows/huggingface-deploy.yml`** runs **pytest**, then **`tools/hf_deploy/deploy_space.py`**, which:

1. Stages a **Docker Space** tree (`Dockerfile`, `pyproject.toml`, `src/`, Space `README.md` from `templates/`).
2. Uses the **`hf`** CLI (from **`huggingface_hub>=1.10`**, entry point **`hf`**, not `huggingface-cli`):
   - `hf auth login --token …`
   - `hf repos create <repo> --repo-type space --space-sdk docker --exist-ok`
   - `hf upload <repo> <stagedir> . --repo-type space --delete "*"` (full mirror commit)
3. Syncs **Space variables**, **secrets**, and **hardware** from **`tools/hf_deploy/profiles/<service>.yaml`** via **`HfApi`** (`add_space_variable`, `add_space_secret`, `request_space_hardware`). The Hub does not yet expose `hf spaces secret set`; add/update at runtime uses those APIs.

Install locally:

```bash
pip install -r tools/hf_deploy/requirements.txt
hf --version
python tools/hf_deploy/deploy_space.py --service lfm_vl_hint --repo-id YOUR_USER/your-space --dry-run
```

## GitHub repository secrets

| Secret | Purpose |
|--------|---------|
| `HF_TOKEN_TONIC` | Write token for **Tonic** Spaces (LFM hints, TerraMind). |
| `HF_TOKEN_NUTONIC` | Write token for **NuTonic** Spaces (game server, PRO materialization). |

Optional **runtime** secrets (see `profiles/*.yaml` — each maps a Hugging Face Space secret key to a **repository secret** whose value is exported under the **same name** as an env var in the deploy job):

| Env var on runner (from GitHub secret) | Used for |
|----------------------------------------|----------|
| `TONIC_LFM_OPENAI_API_KEY` | LFM `openai_compatible` backend |
| `TONIC_LFM_OPENAI_BASE_URL` | Optional OpenAI-compatible base URL |
| `TONIC_TERRAMIND_HF_TOKEN` | Optional Hub token inside TerraMind Space for model pulls |
| `NUTONIC_JWT_SECRET` | Game server Space secret `JWT_SECRET` |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL (often secret) |
| `NUTONIC_RANKED_DATABASE_URL` | Ranked store URL |
| `NUTONIC_MAPBOX_ACCESS_TOKEN` | PRO materialization Mapbox |
| `NUTONIC_INFERENCE_HMAC_SECRET` | PRO worker inbound HMAC |

If an optional secret is **unset**, that key is skipped (no empty secret pushed).

## Profiles

Edit **`tools/hf_deploy/profiles/<service>.yaml`** for production defaults:

- **`variables`**: public Space environment variables (non-secret).
- **`secrets`**: map **Space secret name** → **runner env var name** (CI must export the value).
- **`space_hardware`**: passed to `request_space_hardware` (e.g. `zero-a10g`, `cpu-basic`). Requires an account that can request that flavor.
- **`sleep_time_seconds`**: optional; `-1` means do not sleep on upgraded hardware where supported.

## Default Space repos

| Service | Default `repo_id` |
|---------|-------------------|
| LFM-VL hints | `Tonic/nutonic-lfm-vl-streetview` |
| TerraMind TiM | `Tonic/nutonic-terramind-tim` |
| Game server | `NuTonic/nutonic-game-server` |
| PRO materialization | `NuTonic/nutonic-pro-materialization` |
