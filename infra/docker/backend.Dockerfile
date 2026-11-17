# WaitLess API / worker image. Build from the repository root:
#   docker build -f infra/docker/backend.Dockerfile -t waitless-api .
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .
# Never ship local secrets or test artefacts into the image.
RUN rm -rf .env tests .pytest_cache .ruff_cache uploads/* \
    && useradd --create-home --uid 10001 waitless \
    && mkdir -p /app/uploads && chown -R waitless /app/uploads
USER waitless

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
# One process per container; scale with replicas (Socket.IO state lives in Redis). The worker uses the same
# image with: python -m app.worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
