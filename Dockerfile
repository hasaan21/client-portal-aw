FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpango-1.0-0 \
      libcairo2 \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

COPY run.py ./
COPY migrations ./migrations
COPY scripts ./scripts

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /data/pdfs \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5000

ENV DATABASE_URL=sqlite:////data/portal.db \
    PDF_OUTPUT_DIR=/data/pdfs \
    FLASK_APP=run.py \
    FLASK_ENV=production

# Migrations run then gunicorn starts. Overridable via `command:` in Railway.
CMD ["sh", "-c", "flask db upgrade && gunicorn -w 2 -b 0.0.0.0:${PORT:-5000} --access-logfile - --error-logfile - 'app:create_app()'"]
