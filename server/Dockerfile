# HF Docker Spaces: app_port 7860 — thin game server (no torch)
FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 1000 nutonic

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Default `NUTONIC_LEADERBOARD_DATABASE_URL` writes under `data/` (IMP-060).
RUN mkdir -p /app/data && chown -R nutonic:nutonic /app

USER nutonic

EXPOSE 7860

CMD ["uvicorn", "nutonic_server.main:app", "--host", "0.0.0.0", "--port", "7860"]
