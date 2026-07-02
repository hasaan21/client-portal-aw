"""Login / logout routes."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import bp
from app.auth.forms import LoginForm
from app.extensions import db
from app.models import User


def _is_safe_url(target: str | None) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and parsed.path.startswith("/")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(
            db.select(User).filter_by(email=form.email.data.strip().lower())
        ).scalar_one_or_none()

        if user is None or not user.check_password(form.password.data):
            current_app.logger.info("Failed login attempt for %s", form.email.data)
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", form=form), 401

        login_user(user, remember=form.remember.data)
        current_app.logger.info("User %s signed in", user.email)
        flash(f"Welcome back, {user.name.split()[0]}.", "success")

        next_url = request.args.get("next")
        return redirect(next_url if _is_safe_url(next_url) else url_for("main.index"))

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
