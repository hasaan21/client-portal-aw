FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: build tools for wheels that lack prebuilt linux-arm64 wheels,
# libpango/libcairo for ReportLab image rendering, curl for the healthcheck,
# gosu for the root -> appuser privilege-drop in docker-entrypoint.sh (needed
# because Railway mounts persistent volumes as root at container start).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpango-1.0-0 \
      libcairo2 \
      libjpeg-dev \
      zlib1g-dev \
      curl \
      gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy metadata + source. Layer caching is imperfect because pyproject
# depends on app/__init__.py existing, but the whole install is < 30s.
COPY pyproject.toml README.md ./
COPY app ./app
COPY run.py ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY docker-entrypoint.sh ./docker-entrypoint.sh

RUN pip install --upgrade pip && pip install .

# Create the non-root user + writable data dir. We deliberately do NOT set
# `USER appuser` here — the container has to start as root so the entrypoint
# can chown the Railway-mounted /data volume (mounted as root at container
# start) before dropping privileges via `gosu appuser`.
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /data/pdfs \
    && chown -R appuser:appuser /app /data \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 5000

ENV DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/portal.db \
    PDF_OUTPUT_DIR=/data/pdfs \
    FLASK_APP=run.py \
    FLASK_ENV=production

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-5000}/healthz" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
