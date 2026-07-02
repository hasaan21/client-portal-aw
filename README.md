# AW Client Portal

Internal portal for the AW financial planning team. Enter client data once, capture quarterly balances, run all math automatically, and generate pixel-perfect **SACS** (cashflow) and **TCC** (net worth) PDF reports in minutes instead of a full day.

**Stack:** Flask 3 + SQLAlchemy 2 + Alembic + Flask-Login + Flask-WTF + SQLite + ReportLab.
No frontend framework and no build step — server-rendered Jinja2 templates and a small vanilla-JS design system.

---

## Quick start (local, 5 minutes)

```bash
# 1. Install
make setup                 # creates .venv, installs deps, installs pre-commit hooks, copies .env

# 2. Set up the DB
make upgrade               # applies all Alembic migrations to instance/portal.db

# 3. Seed the three team users (prints one-time passwords)
make seed

# 4. Run
make dev                   # http://localhost:5000
```

Then sign in with any of the printed passwords.

---

## Common commands

| Command                       | What it does                                             |
| ----------------------------- | -------------------------------------------------------- |
| `make dev`                    | Flask dev server on :5000                                |
| `make test`                   | Full pytest suite                                        |
| `make fmt`                    | ruff format + auto-fix                                   |
| `make lint`                   | ruff check (no fixes)                                    |
| `make check`                  | lint + tests (mirrors CI)                                |
| `make migrate M="add foo"`    | Generate a new Alembic migration                         |
| `make upgrade`                | Apply pending migrations                                 |
| `make seed`                   | Create the three team users                              |
| `make pdf-preview CLIENT=1`   | Render both PDFs for client 1 into `instance/pdfs/preview/` (arrives with M4/M5) |
| `make backup`                 | Snapshot the SQLite DB into `./backups/`                 |
| `make docker-build`           | Build the production Docker image                        |

---

## Project layout

```
app/
├── __init__.py          Flask app factory
├── config.py            Dev / Prod / Test configs
├── extensions.py        db / login_manager / csrf singletons
├── models.py            SQLAlchemy models (User, Client, Account, Report, Balance, …)
├── auth/                Login blueprint
├── clients/             Client CRUD (M2)
├── reports/             Report entry + PDF generation (M3–M6)
├── main/                Dashboard
├── calc/engine.py       Pure calculation functions
├── pdf/                 SACS + TCC ReportLab builders (M4/M5)
├── static/              CSS design system, JS, logo
└── templates/           Jinja2 templates
migrations/              Alembic revisions
scripts/                 seed, backup_db, pdf_preview
tests/                   pytest
```

---

## Data model at a glance

- **User** — 3 team members (Andrew, Rebecca, Maryann), argon2 password hash.
- **Client** — household + up to two spouses (`c1_*`, `c2_*`), monthly salary, expense budget, PR target override, PR/trust labels.
- **Account** — belongs to a Client and to a `section` (`SACS_INFLOW` / `SACS_OUTFLOW` / `SACS_PRIVATE_RESERVE` / `SACS_INVESTMENT` / `RETIREMENT` / `NON_RETIREMENT` / `TRUST`) with an `owner` (`CLIENT1` / `CLIENT2` / `JOINT` / `TRUST`). Retirement accounts can never be `JOINT` — enforced by DB CHECK constraint.
- **Liability** — mortgage / auto / health / other, with interest rate.
- **Report** — one per client per meeting date, `DRAFT` or `FINAL`.
- **Balance / LiabilityBalance** — per-report snapshot; `is_stale=true` renders the red `*` marker.
- **InsuranceDeductible** — feeds the PR target formula.
- **AuditLog** — every write on Client / Report is logged.

---

## Calculation rules (from Rebecca's transcript — treat as spec)

- `excess = inflow − outflow` (SACS blue-arrow amount)
- `PR target = 6 × monthly_expenses + Σ insurance_deductibles`
- `retirement_totals`: split per spouse, never joint
- `non_retirement_total` **excludes** trust (24:28)
- `grand_total = C1_retirement + C2_retirement + non_retirement + trust`
- `liabilities` are **always displayed separately, never subtracted** (26:15)

All of the above are implemented in [`app/calc/engine.py`](app/calc/engine.py) as pure functions and are unit-tested exhaustively in `tests/test_calc_engine.py` (arrives with M3).

---

## Deployment (Railway)

1. Push to a GitHub repo, then `railway init` and link the repo.
2. Attach a **persistent volume** mounted at `/data`. All state (SQLite DB, PDFs) lives under `/data` so restarts and redeploys are safe.
3. Set env vars:
   | Var                        | Purpose                                                     |
   | -------------------------- | ----------------------------------------------------------- |
   | `SECRET_KEY`               | **Required.** Cryptographically random string.              |
   | `SESSION_COOKIE_SECURE`    | Set to `true` (Railway serves HTTPS by default).            |
   | `SEED_ON_BOOT`             | `1` = auto-create Andrew/Rebecca/Maryann on first boot.     |
   | `SEED_ADMIN_PASSWORD`      | Fixed initial password (else one is generated & logged).    |
   | `SEED_DEMO`                | `1` = also insert a demo client with a final report.        |
   | `GUNICORN_WORKERS`         | Default `2`.                                                |
   | `GUNICORN_TIMEOUT`         | Default `30` seconds.                                       |
4. Deploy. The [`docker-entrypoint.sh`](docker-entrypoint.sh) sequences:
   1. Verify `/data` is writable
   2. `flask db upgrade` (schema migrations)
   3. First-boot seed if `SEED_ON_BOOT=1` and no users exist
   4. `exec gunicorn` (signals propagate; Railway can graceful-restart)
5. Verify the deploy via `GET /healthz` — returns `{"status": "ok", "db": "reachable"}` when the app + database are both healthy. Railway is configured to route traffic only once this returns 200.

### Backups

Run `python scripts/backup_db.py` on a cron or via `railway run` to snapshot `/data/portal.db` into `/data/backups/YYYY-MM-DD-HHMMSS.db`. For long-term durability you can also rclone the volume to S3/GCS.

### Local production dry-run

```bash
docker build -t aw-portal .
docker run --rm -p 5000:5000 \
  -v aw-portal-data:/data \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e SEED_ON_BOOT=1 \
  -e SEED_ADMIN_PASSWORD=change-me \
  aw-portal
```

---

## License

Proprietary — internal use only.
