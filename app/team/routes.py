"""Team management routes — admin-only.

Layout:
- GET  /team/                                list teammates
- POST /team/invite                          create teammate (temp password shown once)
- POST /team/<id>/reset-password             regenerate password (shown once)
- POST /team/<id>/toggle-admin               flip is_admin flag
- POST /team/<id>/delete                     remove a teammate

Guards:
- @admin_required on every endpoint.
- Cannot delete yourself, cannot demote yourself, cannot delete the last admin.
- Emails are lower-cased and deduplicated on invite.
"""

from __future__ import annotations

import secrets
import string
from functools import wraps

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.audit import record as audit_record
from app.extensions import db
from app.models import User
from app.team import bp
from app.team.forms import EmptyForm, InviteUserForm

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _generate_password(length: int = 16) -> str:
    """Cryptographically-random password. Length 16 is well above the
    LoginForm minimum (6) and easy to paste from a chat message."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def admin_required(fn):
    """403 if the current user is not an admin. Wraps @login_required so
    unauthenticated visitors are redirected to /auth/login as usual."""

    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def _count_admins() -> int:
    return db.session.execute(
        db.select(db.func.count()).select_from(User).where(User.is_admin.is_(True))
    ).scalar_one()


# ---- list ------------------------------------------------------------------


@bp.route("/", endpoint="index")
@admin_required
def list_users():
    users = (
        db.session.execute(db.select(User).order_by(User.is_admin.desc(), User.name))
        .scalars()
        .all()
    )
    return render_template(
        "team/index.html",
        users=users,
        invite_form=InviteUserForm(),
        action_form=EmptyForm(),
    )


# ---- invite ---------------------------------------------------------------


@bp.route("/invite", methods=["POST"], endpoint="invite")
@admin_required
def invite_user():
    form = InviteUserForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for("team.index"))

    email = form.email.data.strip().lower()
    existing = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if existing:
        flash(f"A user with email {email} already exists.", "warning")
        return redirect(url_for("team.index"))

    password = _generate_password()
    user = User(
        email=email,
        name=form.name.data.strip(),
        is_admin=bool(form.is_admin.data),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    audit_record(
        "user",
        user.id,
        "invite",
        {"email": user.email, "is_admin": user.is_admin, "invited_by": current_user.id},
    )
    db.session.commit()

    flash(
        f"Invited {user.name} ({user.email}). Temporary password: {password} — "
        f"share it securely and ask them to change it on first sign-in.",
        "success",
    )
    return redirect(url_for("team.index"))


# ---- reset password -------------------------------------------------------


@bp.route("/<int:user_id>/reset-password", methods=["POST"], endpoint="reset_password")
@admin_required
def reset_password(user_id: int):
    if not EmptyForm().validate_on_submit():
        abort(400)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    password = _generate_password()
    user.set_password(password)
    audit_record("user", user.id, "reset_password", {"by": current_user.id})
    db.session.commit()

    flash(
        f"New password for {user.email}: {password} — share it securely "
        "and have them change it on next sign-in.",
        "success",
    )
    return redirect(url_for("team.index"))


# ---- toggle admin ---------------------------------------------------------


@bp.route("/<int:user_id>/toggle-admin", methods=["POST"], endpoint="toggle_admin")
@admin_required
def toggle_admin(user_id: int):
    if not EmptyForm().validate_on_submit():
        abort(400)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    # Guards: don't demote yourself, don't demote the last admin.
    if user.id == current_user.id:
        flash("You cannot change your own admin status.", "danger")
        return redirect(url_for("team.index"))
    if user.is_admin and _count_admins() <= 1:
        flash("At least one admin must remain.", "danger")
        return redirect(url_for("team.index"))

    user.is_admin = not user.is_admin
    audit_record(
        "user", user.id, "toggle_admin", {"is_admin": user.is_admin, "by": current_user.id}
    )
    db.session.commit()

    verb = "granted" if user.is_admin else "revoked"
    flash(f"Admin access {verb} for {user.email}.", "info")
    return redirect(url_for("team.index"))


# ---- delete ---------------------------------------------------------------


@bp.route("/<int:user_id>/delete", methods=["POST"], endpoint="delete")
@admin_required
def delete_user(user_id: int):
    if not EmptyForm().validate_on_submit():
        abort(400)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("team.index"))
    if user.is_admin and _count_admins() <= 1:
        flash("At least one admin must remain.", "danger")
        return redirect(url_for("team.index"))
    if user.reports:
        flash(
            f"{user.email} has authored {len(user.reports)} report(s) — "
            "revoke their admin access instead of deleting to preserve history.",
            "warning",
        )
        return redirect(url_for("team.index"))

    audit_record("user", user.id, "delete", {"email": user.email, "by": current_user.id})
    db.session.delete(user)
    db.session.commit()

    flash(f"Removed {user.email}.", "info")
    return redirect(url_for("team.index"))
