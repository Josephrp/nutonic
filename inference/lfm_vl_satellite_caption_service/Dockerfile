# Hugging Face Docker Space for the satellite caption service.
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ".[model]"

ENV PORT=7860

EXPOSE 7860

CMD ["uvicorn", "lfm_vl_satellite_caption_service.main:app", "--host", "0.0.0.0", "--port", "7860"]
