# LFM-VL satellite caption service

This worker is the language layer of the NU:TONIC satellite intelligence stack. It takes satellite or map stills and produces human-readable explanations: captions, VQA-style answers, and grounding-oriented JSON that can point downstream tools toward regions of interest.

For the competition story, this is the service that makes satellite AI understandable to non-technical users. TiM and Sentinel-2 pipelines can surface change signals; this VLM turns those signals into language a planner, journalist, judge, or field team can read.

## What it enables

- Plain-language summaries of satellite scenes.
- Structured output for PRO bundles and review interfaces.
- A bridge from model evidence to human decision-making.
- Specialist satellite behavior through the NuTonic fine-tuned LFM-VL path.

## Endpoints

- `GET /health`
- `POST /v1/infer` — satellite still image to caption.
- `POST /v1/pro/caption` — PRO alias with optional profile and contract context.

## Backends

Use `LFM_SATELLITE_BACKEND=stub` for CI and fast local checks. Use `transformers` for the Hugging Face model path, or `openai_compatible` when pointing at a hosted vLLM/SGLang/OpenAI-compatible VLM endpoint.

Typical competition/deploy configuration is managed through `tools/hf_deploy/profiles/lfm_vl_satellite.yaml` and deployed by `.github/workflows/huggingface-deploy.yml`.

## Run locally

```bash
cd inference/lfm_vl_satellite_caption_service
pip install -e ".[dev]"
uvicorn lfm_vl_satellite_caption_service.main:app --host 127.0.0.1 --port 7863
```

Local runs default to the fast stub unless you configure a real backend. GPU is recommended for local `transformers` inference.

## Relationship to Patagonia

The public Patagonia article is [`../../Patagonia_Eval/patagonia_eval_runs/eval.md`](../../Patagonia_Eval/patagonia_eval_runs/eval.md). The service represents the same product idea: a satellite-specialized VLM that can explain observations and, when paired with temporal context, help users reason about change.

## Docker

```bash
docker build -f inference/lfm_vl_satellite_caption_service/Dockerfile -t nutonic-lfm-vl-satellite inference/lfm_vl_satellite_caption_service
```
