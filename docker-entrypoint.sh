#!/usr/bin/env bash
# Production entrypoint used by Railway and any Dockerized deploy.
#
# Order of operations:
#   1. Ensure /data volume exists and is writable.
#   2. Apply pending Alembic migrations.
#   3. First-boot: create the initial admin from BOOTSTRAP_ADMIN_EMAIL /
#      BOOTSTRAP_ADMIN_PASSWORD (idempotent — skips if any user exists).
#      Optionally also insert a demo client when SEED_DEMO=1.
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

# ---- First-boot user provisioning ------------------------------------------
# We deliberately do NOT ship any hardcoded example.com users to production.
# Instead:
#   - BOOTSTRAP_ADMIN_EMAIL creates ONE admin on first boot.
#   - That admin invites the rest of the team via /team in the UI.
#
# scripts/bootstrap_admin.py is idempotent — it no-ops as soon as any user
# exists, so container restarts never re-print passwords.
if [[ -n "${BOOTSTRAP_ADMIN_EMAIL:-}" ]]; then
  python scripts/bootstrap_admin.py
else
  echo "[entrypoint] BOOTSTRAP_ADMIN_EMAIL not set — skipping admin bootstrap."
fi

# Optional demo-client seed (still guarded by SEED_DEMO=1). Runs only when at
# least one user exists so the audit log has an author to attribute the demo
# writes to. Idempotent via a --demo-only flag that skips user creation.
if [[ "${SEED_DEMO:-0}" == "1" ]]; then
  echo "[entrypoint] SEED_DEMO=1 — inserting demo client if missing"
  python scripts/seed.py --demo --demo-only || echo "[entrypoint] demo seed skipped (already present or no user)"
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
