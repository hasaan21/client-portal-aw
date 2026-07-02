"""Dashboard / landing page."""

from __future__ import annotations

from flask import render_template
from flask_login import login_required

from app.extensions import db
from app.main import bp
from app.models import Client, Report, ReportStatus


@bp.route("/")
@login_required
def index():
    active_clients = db.session.execute(
        db.select(db.func.count()).select_from(Client).where(Client.archived_at.is_(None))
    ).scalar_one()
    final_reports = db.session.execute(
        db.select(db.func.count()).select_from(Report).where(Report.status == ReportStatus.FINAL)
    ).scalar_one()
    draft_reports = db.session.execute(
        db.select(db.func.count()).select_from(Report).where(Report.status == ReportStatus.DRAFT)
    ).scalar_one()

    recent_reports = (
        db.session.execute(db.select(Report).order_by(Report.created_at.desc()).limit(8))
        .scalars()
        .all()
    )

    return render_template(
        "main/index.html",
        active_clients=active_clients,
        final_reports=final_reports,
        draft_reports=draft_reports,
        recent_reports=recent_reports,
    )
