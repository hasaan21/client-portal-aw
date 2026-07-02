"""Dashboard / landing page."""

from __future__ import annotations

from flask import render_template
from flask_login import login_required

from app.extensions import db
from app.main import bp
from app.models import Client, Report


@bp.route("/")
@login_required
def index():
    client_count = db.session.execute(
        db.select(db.func.count()).select_from(Client).where(Client.archived_at.is_(None))
    ).scalar_one()
    report_count = db.session.execute(db.select(db.func.count()).select_from(Report)).scalar_one()

    recent_reports = (
        db.session.execute(db.select(Report).order_by(Report.created_at.desc()).limit(5))
        .scalars()
        .all()
    )

    return render_template(
        "main/index.html",
        client_count=client_count,
        report_count=report_count,
        recent_reports=recent_reports,
    )
