# WaitLess API / worker image. Build from the repository root:
#   docker build -f infra/docker/backend.Dockerfile -t waitless-api .
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .
RUN useradd --create-home --uid 10001 waitless && mkdir -p /app/uploads && chown -R waitless /app/uploads
USER waitless

EXPOSE 8000
# The worker uses the same image with: python -m app.worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
