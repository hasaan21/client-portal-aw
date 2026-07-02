#!/usr/bin/env bash
# Production entrypoint used by Railway and any Dockerized deploy.
#
# Order of operations:
#   1. Ensure /data volume exists and is writable.
#   2. Apply pending Alembic migrations.
#   3. First-boot: if SEED_ON_BOOT=1 and no users exist, run the seed script.
#   4. Exec gunicorn (replacing this shell so signals propagate cleanly).

set -euo pipefail

echo "[entrypoint] starting AW Client Portal"

DATA_DIR="${DATA_DIR:-/data}"
PDF_DIR="${PDF_OUTPUT_DIR:-${DATA_DIR}/pdfs}"

mkdir -p "$DATA_DIR" "$PDF_DIR"

if [[ ! -w "$DATA_DIR" ]]; then
  echo "[entrypoint] FATAL: $DATA_DIR is not writable" >&2
  exit 1
fi

echo "[entrypoint] applying migrations..."
flask db upgrade

if [[ "${SEED_ON_BOOT:-0}" == "1" ]]; then
  # Only seed if no users exist yet, so restarts don't re-print passwords.
  users_present=$(python -c "
from app import create_app
from app.extensions import db
from app.models import User
app = create_app()
with app.app_context():
    count = db.session.execute(db.select(db.func.count()).select_from(User)).scalar_one()
    print(count)
")
  if [[ "$users_present" == "0" ]]; then
    echo "[entrypoint] first boot detected — seeding users"
    python scripts/seed.py ${SEED_DEMO:+--demo}
  else
    echo "[entrypoint] users already exist — skipping seed"
  fi
fi

PORT="${PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-2}"
TIMEOUT="${GUNICORN_TIMEOUT:-30}"

echo "[entrypoint] starting gunicorn on :$PORT ($WORKERS workers)"
exec gunicorn \
  --workers "$WORKERS" \
  --bind "0.0.0.0:$PORT" \
  --timeout "$TIMEOUT" \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips '*' \
  'app:create_app()'
