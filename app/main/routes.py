"""Dashboard + audit log."""

from __future__ import annotations

from flask import render_template, request
from flask_login import login_required

from app.extensions import db
from app.main import bp
from app.models import AuditLog, Client, Report, ReportStatus, User


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


@bp.route("/audit")
@login_required
def audit_log():
    """Read-only audit trail. Available to any signed-in user (all 3 team
    members are essentially admins in this deployment)."""

    entity_filter = request.args.get("entity", "")
    action_filter = request.args.get("action", "")
    limit = min(int(request.args.get("limit", 200) or 200), 1000)

    stmt = db.select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit)
    if entity_filter:
        stmt = stmt.where(AuditLog.entity == entity_filter)
    if action_filter:
        stmt = stmt.where(AuditLog.action == action_filter)

    entries = db.session.execute(stmt).scalars().all()
    users = {u.id: u for u in db.session.execute(db.select(User)).scalars().all()}

    return render_template(
        "main/audit_log.html",
        entries=entries,
        users=users,
        entity_filter=entity_filter,
        action_filter=action_filter,
        limit=limit,
    )
