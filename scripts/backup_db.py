"""Timestamped SQLite backup.

Copies the current DB file into ./backups/portal-YYYYMMDD-HHMMSS.db
(a hard link when possible; SQLite's built-in backup API when not).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app


def resolve_db_path(app) -> Path:
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    parsed = urlparse(uri)
    if parsed.scheme != "sqlite":
        raise SystemExit(f"backup_db.py only supports sqlite:// URIs — got {uri}")
    return Path(parsed.path)


def main() -> int:
    app = create_app()
    src = resolve_db_path(app)
    if not src.exists():
        print(f"! DB not found at {src}", file=sys.stderr)
        return 1

    backup_dir = Path("backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"portal-{ts}.db"

    try:
        with sqlite3.connect(src) as src_conn, sqlite3.connect(dst) as dst_conn:
            src_conn.backup(dst_conn)
    except sqlite3.Error:
        shutil.copy2(src, dst)

    print(f"+ backed up  {src}  ->  {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
