"""Create the initial admin user from environment variables.

Called by `docker-entrypoint.sh` on every boot. Idempotent:

- If any user already exists, this script is a no-op (prevents password
  leaks in redeploy logs and stops accidentally overriding a real user).
- Otherwise, it creates one admin using:
    BOOTSTRAP_ADMIN_EMAIL     required — the admin's real email
    BOOTSTRAP_ADMIN_NAME      optional — defaults to the email local-part
    BOOTSTRAP_ADMIN_PASSWORD  optional — if omitted, a random 16-char
                              password is generated and printed to stdout.

The generated password appears in the deploy logs exactly once. Copy it
into a password manager immediately; the admin should change it on
first sign-in via Team → Reset password.

Once the initial admin is in place, they invite the rest of the team
through the in-app Team page — no code / env changes needed thereafter.
"""

from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models import User


def _generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _default_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = local.replace(".", " ").replace("_", " ").split()
    return " ".join(p.capitalize() for p in parts) or email


def main() -> int:
    app = create_app()
    with app.app_context():
        existing_count = db.session.execute(
            db.select(db.func.count()).select_from(User)
        ).scalar_one()
        if existing_count > 0:
            print(
                f"[bootstrap] {existing_count} user(s) already exist — skipping bootstrap admin.",
            )
            return 0

        email_raw = os.environ.get("BOOTSTRAP_ADMIN_EMAIL")
        if not email_raw:
            print(
                "[bootstrap] BOOTSTRAP_ADMIN_EMAIL not set — refusing to seed. "
                "Set it in Railway variables and redeploy to create the first admin.",
                file=sys.stderr,
            )
            return 0  # not fatal — the app boots, /auth/login just has no users

        email = email_raw.strip().lower()
        name = (os.environ.get("BOOTSTRAP_ADMIN_NAME") or "").strip() or _default_name_from_email(
            email
        )
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or _generate_password()
        password_generated = "BOOTSTRAP_ADMIN_PASSWORD" not in os.environ

        admin = User(email=email, name=name, is_admin=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        print(f"[bootstrap] Created admin {email} ({name}).")
        if password_generated:
            # The ONLY place we log a plaintext password — copy it now.
            print(
                f"[bootstrap] Generated password for {email}: {password}",
                flush=True,
            )
            print(
                "[bootstrap] Rotate this password on first sign-in via Team → Reset password.",
            )
        else:
            print("[bootstrap] Used BOOTSTRAP_ADMIN_PASSWORD from environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
