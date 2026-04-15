FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
EXPOSE 8080
CMD ["uvicorn", "pro_materialization_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
