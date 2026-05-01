FROM python:3.12-slim-bookworm
WORKDIR /app

# Rasterio needs GDAL/PROJ/GEOS at runtime; slim images omit them. Fail the image build if imports break.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir . \
    && python -c "import rasterio, rasterio.warp; import pystac_client; print('s2 imports ok')"
EXPOSE 7860
CMD ["uvicorn", "pro_materialization_service.main:app", "--host", "0.0.0.0", "--port", "7860"]
