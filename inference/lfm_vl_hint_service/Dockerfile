# Hugging Face Docker Space — ZeroGPU + Gradio at /gradio + REST (see README.md).
# Base image supplies CUDA for transformers + @spaces.GPU forwards.
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ".[serve,model]"

ENV LFM_VL_MOUNT_GRADIO=1
ENV PORT=7860

EXPOSE 7860

CMD ["python", "-m", "lfm_vl_hint_service.run_serve"]
