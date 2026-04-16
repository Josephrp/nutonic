# Hugging Face Space deploy (NU:TONIC)

GitHub Actions workflow **`.github/workflows/huggingface-deploy.yml`** runs **pytest** for the affected Python package, then uploads a **Docker Space** layout to Hugging Face using `tools/hf_deploy/upload_space.py`.

## Repository secrets

| Secret | Used for |
|--------|----------|
| `HF_TOKEN_TONIC` | Write token for Spaces under HF user/org **Tonic** (GPU / ZeroGPU services). |
| `HF_TOKEN_NUTONIC` | Write token for Spaces under HF user/org **NuTonic** (game server + PRO materialization). |

Create Spaces once manually if you prefer; the script calls `create_repo(..., exist_ok=True)` so missing repos are created when the token has permission.

**Token scope:** fine-grained or classic token with **write** access to the target Space repos (and **read** to Hub if models download at runtime).

## Default Space names

| Service | Default `repo_id` | HF owner |
|---------|-------------------|----------|
| LFM-VL Street View hints | `Tonic/nutonic-lfm-vl-streetview` | Tonic |
| TerraMind TiM local | `Tonic/nutonic-terramind-tim` | Tonic |
| Game server | `NuTonic/nutonic-game-server` | NuTonic |
| PRO materialization | `NuTonic/nutonic-pro-materialization` | NuTonic |

Override with workflow_dispatch inputs if your usernames or repo names differ.

## Gradio + ZeroGPU (GPU Spaces)

The **LFM-VL hints** image sets `LFM_VL_MOUNT_GRADIO=1` and installs `[serve,model]`, matching `inference/lfm_vl_hint_service/README.md`: **Gradio** is mounted at **`/gradio`** on the same ASGI app as FastAPI (Docker Space, not pure `sdk: gradio` file layout). On Hugging Face, pick **ZeroGPU** hardware so `@spaces.GPU` forwards run.

## Local dry run

```bash
cd /path/to/nutonic/repo
python -m venv .venv-hf && .venv-hf/Scripts/activate  # or source .venv-hf/bin/activate
pip install -r tools/hf_deploy/requirements.txt
python tools/hf_deploy/upload_space.py --service lfm_vl_hint --repo-id YOUR_USER/your-space --dry-run
```

Dry run does not require `HF_TOKEN`.
