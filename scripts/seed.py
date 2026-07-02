"""Seed the three team users described in the PRD.

Usage:
    python scripts/seed.py

Idempotent: re-running only updates missing fields, never overwrites hashes.

Passwords are printed to stdout the FIRST time a user is created and then never
again. Save them in your password manager immediately.
"""

from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

# Ensure project root is on the path when invoked as ``python scripts/seed.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models import User

TEAM = [
    {"email": "andrew@example.com", "name": "Andrew Windbrook", "is_admin": True},
    {"email": "rebecca@example.com", "name": "Rebecca Planner", "is_admin": False},
    {"email": "maryann@example.com", "name": "Maryann Assistant", "is_admin": False},
]


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def seed() -> int:
    app = create_app()
    created = 0
    with app.app_context():
        db.create_all()
        for spec in TEAM:
            existing = db.session.execute(
                db.select(User).filter_by(email=spec["email"])
            ).scalar_one_or_none()
            if existing:
                print(f"= exists     {spec['email']}")
                continue

            password = os.environ.get("SEED_ADMIN_PASSWORD") or _generate_password()
            user = User(email=spec["email"], name=spec["name"], is_admin=spec["is_admin"])
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            created += 1
            print(f"+ created    {spec['email']:32s}  password: {password}")

        print(f"\n{created} user(s) created; {len(TEAM) - created} already existed.")
    return created


if __name__ == "__main__":
    raise SystemExit(0 if seed() >= 0 else 1)
