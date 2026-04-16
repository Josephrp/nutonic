# Hugging Face Docker Space — TerraMind TiM (TerraTorch). Select ZeroGPU hardware on the Space.
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ".[space]"

ENV PORT=7860

EXPOSE 7860

CMD ["python", "-m", "nutonic_terramind_tim_local.run_space_serve"]
