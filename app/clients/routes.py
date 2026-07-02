"""Client CRUD routes.

Layout:
- GET  /clients/                       list
- GET  /clients/new                    empty household form
- POST /clients/new                    create
- GET  /clients/<id>                   detail (accounts, liabilities, deductibles panels)
- GET  /clients/<id>/edit              edit household basics
- POST /clients/<id>/edit              update household
- POST /clients/<id>/archive           soft-delete (sets archived_at)
- POST /clients/<id>/restore           un-archive
- POST /clients/<id>/accounts/new      add an account
- POST /clients/<id>/accounts/<aid>/delete
- POST /clients/<id>/liabilities/new
- POST /clients/<id>/liabilities/<lid>/delete
- POST /clients/<id>/deductibles/new
- POST /clients/<id>/deductibles/<did>/delete
"""

from __future__ import annotations

from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.audit import record as audit_record
from app.clients import bp
from app.clients.forms import (
    AccountForm,
    ClientHouseholdForm,
    DeductibleForm,
    DeleteForm,
    LiabilityForm,
)
from app.extensions import db
from app.models import (
    Account,
    AccountKind,
    AccountOwner,
    AccountSection,
    Client,
    InsuranceDeductible,
    Liability,
    LiabilityKind,
)


def _get_client_or_404(client_id: int) -> Client:
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)
    return client


def _form_to_client_kwargs(form: ClientHouseholdForm) -> dict:
    """Extract cleaned values for Client.__init__ / setattr."""
    return {
        "household_label": form.household_label.data.strip(),
        "c1_first": form.c1_first.data.strip(),
        "c1_last": form.c1_last.data.strip(),
        "c1_dob": form.c1_dob.data,
        "c1_ssn_last4": form.c1_ssn_last4.data.strip(),
        "c1_monthly_salary": form.c1_monthly_salary.data,
        "c2_first": (form.c2_first.data or None) and form.c2_first.data.strip(),
        "c2_last": (form.c2_last.data or None) and form.c2_last.data.strip(),
        "c2_dob": form.c2_dob.data or None,
        "c2_ssn_last4": (form.c2_ssn_last4.data or None) and form.c2_ssn_last4.data.strip(),
        "c2_monthly_salary": form.c2_monthly_salary.data or None,
        "monthly_expense_budget": form.monthly_expense_budget.data,
        "private_reserve_target_override": form.private_reserve_target_override.data or None,
        "private_reserve_label": form.private_reserve_label.data.strip(),
        "trust_label": form.trust_label.data.strip(),
        "trust_property_address": form.trust_property_address.data or None,
    }


# ---- list ------------------------------------------------------------------


@bp.route("/", endpoint="index")
@login_required
def list_clients():
    show_archived = request.args.get("archived") == "1"
    stmt = db.select(Client).order_by(Client.household_label)
    if not show_archived:
        stmt = stmt.where(Client.archived_at.is_(None))
    clients = db.session.execute(stmt).scalars().all()

    archive_form = DeleteForm()
    return render_template(
        "clients/list.html",
        clients=clients,
        show_archived=show_archived,
        archive_form=archive_form,
    )


# ---- new / create ----------------------------------------------------------


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_client():
    form = ClientHouseholdForm()
    if form.validate_on_submit():
        client = Client(**_form_to_client_kwargs(form))
        db.session.add(client)
        db.session.flush()  # get id for audit
        audit_record("client", client.id, "create", {"household_label": client.household_label})
        db.session.commit()
        flash(f"Client '{client.display_name}' created.", "success")
        return redirect(url_for("clients.detail", client_id=client.id))

    return render_template("clients/new.html", form=form)


# ---- detail ----------------------------------------------------------------


@bp.route("/<int:client_id>", endpoint="detail")
@login_required
def detail(client_id: int):
    client = _get_client_or_404(client_id)

    account_form = AccountForm()
    liability_form = LiabilityForm()
    deductible_form = DeductibleForm()
    delete_form = DeleteForm()

    return render_template(
        "clients/detail.html",
        client=client,
        account_form=account_form,
        liability_form=liability_form,
        deductible_form=deductible_form,
        delete_form=delete_form,
    )


# ---- edit household --------------------------------------------------------


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id: int):
    client = _get_client_or_404(client_id)
    form = ClientHouseholdForm(obj=client)

    if form.validate_on_submit():
        new_values = _form_to_client_kwargs(form)
        before = {k: getattr(client, k) for k in new_values}
        for k, v in new_values.items():
            setattr(client, k, v)
        diff = {
            k: [str(before[k]), str(getattr(client, k))]
            for k in before
            if before[k] != getattr(client, k)
        }
        audit_record("client", client.id, "update", diff)
        db.session.commit()
        flash("Client updated.", "success")
        return redirect(url_for("clients.detail", client_id=client.id))

    return render_template("clients/edit.html", form=form, client=client)


# ---- archive / restore -----------------------------------------------------


@bp.route("/<int:client_id>/archive", methods=["POST"])
@login_required
def archive(client_id: int):
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    client = _get_client_or_404(client_id)
    client.archived_at = datetime.utcnow()
    audit_record("client", client.id, "archive")
    db.session.commit()
    flash(f"Client '{client.display_name}' archived.", "info")
    return redirect(url_for("clients.index"))


@bp.route("/<int:client_id>/restore", methods=["POST"])
@login_required
def restore(client_id: int):
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    client = _get_client_or_404(client_id)
    client.archived_at = None
    audit_record("client", client.id, "restore")
    db.session.commit()
    flash(f"Client '{client.display_name}' restored.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


# ---- accounts --------------------------------------------------------------


@bp.route("/<int:client_id>/accounts/new", methods=["POST"])
@login_required
def add_account(client_id: int):
    client = _get_client_or_404(client_id)
    form = AccountForm()
    if not form.validate_on_submit():
        for _, errs in form.errors.items():
            for e in errs:
                flash(e, "danger")
        return redirect(url_for("clients.detail", client_id=client.id))

    max_idx = max((a.order_idx for a in client.accounts), default=-1)
    account = Account(
        client_id=client.id,
        section=AccountSection(form.section.data),
        owner=AccountOwner(form.owner.data),
        kind=AccountKind(form.kind.data),
        display_name=form.display_name.data or None,
        custodian=form.custodian.data or None,
        last4=form.last4.data or None,
        order_idx=max_idx + 1,
    )
    db.session.add(account)
    db.session.flush()
    audit_record(
        "account",
        account.id,
        "create",
        {"client_id": client.id, "section": account.section.value, "kind": account.kind.value},
    )
    db.session.commit()
    flash("Account added.", "success")
    return redirect(url_for("clients.detail", client_id=client.id) + "#accounts")


@bp.route("/<int:client_id>/accounts/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_account(client_id: int, account_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    client = _get_client_or_404(client_id)
    account = db.session.get(Account, account_id)
    if not account or account.client_id != client.id:
        abort(404)
    audit_record(
        "account", account.id, "delete", {"client_id": client.id, "kind": account.kind.value}
    )
    db.session.delete(account)
    db.session.commit()
    flash("Account removed.", "info")
    return redirect(url_for("clients.detail", client_id=client.id) + "#accounts")


# ---- liabilities -----------------------------------------------------------


@bp.route("/<int:client_id>/liabilities/new", methods=["POST"])
@login_required
def add_liability(client_id: int):
    client = _get_client_or_404(client_id)
    form = LiabilityForm()
    if not form.validate_on_submit():
        for _, errs in form.errors.items():
            for e in errs:
                flash(e, "danger")
        return redirect(url_for("clients.detail", client_id=client.id) + "#liabilities")

    max_idx = max((lb.order_idx for lb in client.liabilities), default=-1)
    liability = Liability(
        client_id=client.id,
        kind=LiabilityKind(form.kind.data),
        label=form.label.data.strip(),
        interest_rate=form.interest_rate.data,
        order_idx=max_idx + 1,
    )
    db.session.add(liability)
    db.session.flush()
    audit_record(
        "liability", liability.id, "create", {"client_id": client.id, "label": liability.label}
    )
    db.session.commit()
    flash("Liability added.", "success")
    return redirect(url_for("clients.detail", client_id=client.id) + "#liabilities")


@bp.route("/<int:client_id>/liabilities/<int:liability_id>/delete", methods=["POST"])
@login_required
def delete_liability(client_id: int, liability_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    client = _get_client_or_404(client_id)
    liability = db.session.get(Liability, liability_id)
    if not liability or liability.client_id != client.id:
        abort(404)
    audit_record("liability", liability.id, "delete", {"client_id": client.id})
    db.session.delete(liability)
    db.session.commit()
    flash("Liability removed.", "info")
    return redirect(url_for("clients.detail", client_id=client.id) + "#liabilities")


# ---- deductibles -----------------------------------------------------------


@bp.route("/<int:client_id>/deductibles/new", methods=["POST"])
@login_required
def add_deductible(client_id: int):
    client = _get_client_or_404(client_id)
    form = DeductibleForm()
    if not form.validate_on_submit():
        for _, errs in form.errors.items():
            for e in errs:
                flash(e, "danger")
        return redirect(url_for("clients.detail", client_id=client.id) + "#deductibles")

    deductible = InsuranceDeductible(
        client_id=client.id,
        label=form.label.data.strip(),
        amount=form.amount.data,
    )
    db.session.add(deductible)
    db.session.flush()
    audit_record("deductible", deductible.id, "create", {"client_id": client.id})
    db.session.commit()
    flash("Deductible added.", "success")
    return redirect(url_for("clients.detail", client_id=client.id) + "#deductibles")


@bp.route("/<int:client_id>/deductibles/<int:deductible_id>/delete", methods=["POST"])
@login_required
def delete_deductible(client_id: int, deductible_id: int):
    if not DeleteForm().validate_on_submit():
        abort(400)
    client = _get_client_or_404(client_id)
    deductible = db.session.get(InsuranceDeductible, deductible_id)
    if not deductible or deductible.client_id != client.id:
        abort(404)
    audit_record("deductible", deductible.id, "delete", {"client_id": client.id})
    db.session.delete(deductible)
    db.session.commit()
    flash("Deductible removed.", "info")
    return redirect(url_for("clients.detail", client_id=client.id) + "#deductibles")
