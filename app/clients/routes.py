"""Client CRUD routes. Placeholder — implemented in M2."""

from __future__ import annotations

from flask import render_template
from flask_login import login_required

from app.clients import bp


@bp.route("/")
@login_required
def index():
    return render_template("clients/placeholder.html")
