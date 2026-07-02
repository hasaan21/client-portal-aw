"""Quarterly report entry + finalization routes.

- GET  /reports/                          index (recent reports)
- GET  /reports/new/<client_id>           new-report meeting-date form
- POST /reports/new/<client_id>           create + redirect to entry
- GET  /reports/<report_id>               entry / detail
- POST /reports/<report_id>               save balances (still DRAFT)
- POST /reports/<report_id>/finalize      mark FINAL + trigger PDF gen (PDFs in M4/M5)
- POST /reports/<report_id>/reopen        move FINAL -> DRAFT (audit-tracked)
- POST /reports/<report_id>/live-totals   JSON endpoint powering the sticky footer
- POST /reports/<report_id>/delete        remove a draft (never a FINAL)
"""

from __future__ import annotations

from datetime import datetime

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.audit import record as audit_record
from app.clients.forms import DeleteForm
from app.extensions import db
from app.models import Client, Report, ReportStatus
from app.pdf.orchestrator import generate_all
from app.reports import bp
from app.reports.forms import NewReportForm
from app.reports.services import (
    apply_form_to_balances,
    build_entry_context,
    compute_totals,
    scaffold_new_report,
    totals_from_report,
)


def _get_report_or_404(report_id: int) -> Report:
    r = db.session.get(Report, report_id)
    if r is None:
        abort(404)
    return r


def _get_client_or_404(client_id: int) -> Client:
    c = db.session.get(Client, client_id)
    if c is None:
        abort(404)
    return c


# ---- index -----------------------------------------------------------------


@bp.route("/", endpoint="index")
@login_required
def index():
    reports = (
        db.session.execute(db.select(Report).order_by(Report.created_at.desc()).limit(50))
        .scalars()
        .all()
    )
    return render_template("reports/index.html", reports=reports)


# ---- new -------------------------------------------------------------------


@bp.route("/new/<int:client_id>", methods=["GET", "POST"])
@login_required
def new_report(client_id: int):
    client = _get_client_or_404(client_id)
    form = NewReportForm()

    if form.validate_on_submit():
        try:
            report = scaffold_new_report(client, form.meeting_date.data, current_user.id)
            audit_record(
                "report",
                report.id,
                "create",
                {"client_id": client.id, "meeting_date": str(report.meeting_date)},
            )
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("A report already exists for that meeting date.", "danger")
            return render_template("reports/new.html", form=form, client=client)

        flash("Draft report created. Enter this quarter's balances.", "success")
        return redirect(url_for("reports.detail", report_id=report.id))

    return render_template("reports/new.html", form=form, client=client)


# ---- detail / entry --------------------------------------------------------


@bp.route("/<int:report_id>", methods=["GET", "POST"])
@login_required
def detail(report_id: int):
    report = _get_report_or_404(report_id)

    if request.method == "POST":
        if report.is_final:
            flash("This report is final. Reopen it before editing.", "warning")
            return redirect(url_for("reports.detail", report_id=report.id))
        errors = apply_form_to_balances(report, request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            audit_record("report", report.id, "update-balances")
            db.session.commit()
            flash("Balances saved.", "success")
        return redirect(url_for("reports.detail", report_id=report.id))

    ctx = build_entry_context(report)
    totals = totals_from_report(report)
    delete_form = DeleteForm()
    return render_template(
        "reports/detail.html",
        report=report,
        ctx=ctx,
        totals=totals,
        delete_form=delete_form,
    )


# ---- finalize --------------------------------------------------------------


@bp.route("/<int:report_id>/finalize", methods=["POST"])
@login_required
def finalize(report_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    report = _get_report_or_404(report_id)
    if report.is_final:
        flash("Report already finalized.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))

    report.status = ReportStatus.FINAL
    report.generated_at = datetime.utcnow()
    audit_record("report", report.id, "finalize")
    db.session.flush()

    outputs = generate_all(report)
    if "sacs" in outputs:
        report.sacs_pdf_path = outputs["sacs"]
    if "tcc" in outputs:
        report.tcc_pdf_path = outputs["tcc"]
    db.session.commit()

    current_app.logger.info(
        "Report %s finalized for client %s by %s (%d PDFs generated)",
        report.id,
        report.client_id,
        current_user.email,
        len(outputs),
    )

    if not outputs:
        flash("Report finalized. PDF builders ship in later milestones.", "success")
    else:
        flash(
            f"Report finalized. Generated: {', '.join(outputs.keys()).upper()}.",
            "success",
        )
    return redirect(url_for("reports.detail", report_id=report.id))


# ---- PDF downloads ---------------------------------------------------------


@bp.route("/<int:report_id>/pdf/<kind>")
@login_required
def download_pdf(report_id: int, kind: str):
    if kind not in ("sacs", "tcc"):
        abort(404)
    report = _get_report_or_404(report_id)
    path = report.sacs_pdf_path if kind == "sacs" else report.tcc_pdf_path
    if not path:
        # Try regenerating on demand (useful in dev after enabling a builder).
        outputs = generate_all(report)
        if kind not in outputs:
            abort(404)
        if kind == "sacs":
            report.sacs_pdf_path = outputs["sacs"]
        else:
            report.tcc_pdf_path = outputs["tcc"]
        db.session.commit()
        path = outputs[kind]
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=True, download_name=p.name, mimetype="application/pdf")


# ---- reopen ----------------------------------------------------------------


@bp.route("/<int:report_id>/reopen", methods=["POST"])
@login_required
def reopen(report_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    report = _get_report_or_404(report_id)
    if not report.is_final:
        flash("Only finalized reports can be reopened.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))
    report.status = ReportStatus.DRAFT
    audit_record("report", report.id, "reopen")
    db.session.commit()
    flash("Report reopened for edits.", "info")
    return redirect(url_for("reports.detail", report_id=report.id))


# ---- delete draft ----------------------------------------------------------


@bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
def delete(report_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    report = _get_report_or_404(report_id)
    if report.is_final:
        flash("Cannot delete a finalized report. Reopen first if you must.", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    client_id = report.client_id
    audit_record("report", report.id, "delete")
    db.session.delete(report)
    db.session.commit()
    flash("Draft deleted.", "info")
    return redirect(url_for("clients.detail", client_id=client_id))


# ---- live totals (JSON) ----------------------------------------------------


@bp.route("/<int:report_id>/live-totals", methods=["POST"])
@login_required
def live_totals(report_id: int):
    report = _get_report_or_404(report_id)

    balances_by_account: dict[int, str] = {}
    liability_balances: dict[int, str] = {}
    stale_flags: dict[int, bool] = {}

    for account in report.client.accounts:
        key = f"balance_{account.id}"
        if key in request.form:
            balances_by_account[account.id] = request.form[key]
        stale_flags[account.id] = request.form.get(f"stale_{account.id}") in (
            "on",
            "true",
            "1",
        )

    for liab in report.client.liabilities:
        key = f"liab_balance_{liab.id}"
        if key in request.form:
            liability_balances[liab.id] = request.form[key]

    from decimal import Decimal

    totals = compute_totals(
        report.client,
        {k: Decimal(v or "0") for k, v in balances_by_account.items()},
        {k: Decimal(v or "0") for k, v in liability_balances.items()},
        stale_flags,
    )
    return jsonify(totals.as_dict())
