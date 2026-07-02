"""Report entry + generation routes. Placeholder — implemented in M3\u2013M6."""

from __future__ import annotations

from flask import render_template
from flask_login import login_required

from app.reports import bp


@bp.route("/")
@login_required
def index():
    return render_template("reports/placeholder.html")
