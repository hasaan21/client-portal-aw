"""Report-entry flow tests (M3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

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
    Report,
    ReportStatus,
    User,
)
from app.reports.services import (
    apply_form_to_balances,
    build_entry_context,
    compute_totals,
    scaffold_new_report,
    totals_from_report,
)

D = Decimal


@pytest.fixture()
def rich_client(app, user_factory):
    """A married client with a realistic full account/liability layout."""
    user_factory(email="andrew@example.com")
    with app.app_context():
        c = Client(
            household_label="The Smiths",
            c1_first="John",
            c1_last="Smith",
            c1_dob=date(1970, 5, 14),
            c1_ssn_last4="1234",
            c1_monthly_salary=D("8000"),
            c2_first="Jane",
            c2_last="Smith",
            c2_dob=date(1972, 3, 22),
            c2_ssn_last4="5678",
            c2_monthly_salary=D("7000"),
            monthly_expense_budget=D("12000"),
            trust_label="Smith Family Trust",
        )
        db.session.add(c)
        db.session.flush()

        # SACS accounts (roles)
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_INFLOW,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
                order_idx=0,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_OUTFLOW,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
                order_idx=1,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_PRIVATE_RESERVE,
                owner=AccountOwner.JOINT,
                kind=AccountKind.HYSA,
                order_idx=2,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_INVESTMENT,
                owner=AccountOwner.JOINT,
                kind=AccountKind.BROKERAGE,
                order_idx=3,
            )
        )
        # Retirement (per spouse)
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT1,
                kind=AccountKind.ROTH_IRA,
                order_idx=4,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT2,
                kind=AccountKind._401K,
                order_idx=5,
            )
        )
        # Non-retirement
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.NON_RETIREMENT,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
                display_name="Wells Fargo Main",
                order_idx=6,
            )
        )
        # Trust
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.TRUST,
                owner=AccountOwner.TRUST,
                kind=AccountKind.OTHER,
                order_idx=7,
            )
        )

        # Liabilities
        db.session.add(
            Liability(
                client_id=c.id,
                kind=LiabilityKind.MORTGAGE,
                label="P Mortg",
                interest_rate=D("6.125"),
                order_idx=0,
            )
        )
        db.session.add(
            Liability(
                client_id=c.id,
                kind=LiabilityKind.AUTO,
                label="Mercedes",
                interest_rate=D("4.5"),
                order_idx=1,
            )
        )

        # Deductibles feed PR target
        db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
        db.session.add(InsuranceDeductible(client_id=c.id, label="Home", amount=D("2000")))

        db.session.commit()
        return c.id


def _get_user_id(app):
    with app.app_context():
        return db.session.execute(db.select(User.id).limit(1)).scalar_one()


# ---- scaffold_new_report --------------------------------------------------


def test_scaffold_creates_balances_for_every_account(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)
        r = scaffold_new_report(client, date.today(), uid)
        db.session.commit()

        assert len(r.balances) == len(client.accounts)
        assert len(r.liability_balances) == len(client.liabilities)
        assert r.status == ReportStatus.DRAFT
        assert all(b.balance == D("0.00") for b in r.balances)


def test_scaffold_prefills_from_previous_final(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)

        r1 = scaffold_new_report(client, date(2024, 1, 15), uid)
        db.session.commit()
        # Fill r1 with realistic balances and finalize it.
        for b in r1.balances:
            b.balance = D("500")
        r1.status = ReportStatus.FINAL
        db.session.commit()

        r2 = scaffold_new_report(client, date(2024, 4, 15), uid)
        db.session.commit()
        assert all(b.balance == D("500") for b in r2.balances)


def test_scaffold_ignores_draft_previous_reports(app, rich_client):
    """Only FINAL reports should be treated as 'last quarter's value'."""
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)

        r1 = scaffold_new_report(client, date(2024, 1, 15), uid)
        db.session.commit()
        for b in r1.balances:
            b.balance = D("999")
        # r1 stays DRAFT

        r2 = scaffold_new_report(client, date(2024, 4, 15), uid)
        db.session.commit()
        assert all(b.balance == D("0.00") for b in r2.balances)


# ---- compute_totals -------------------------------------------------------


def test_compute_totals_end_to_end(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)
        r = scaffold_new_report(client, date.today(), uid)
        db.session.commit()

        by_account = {b.account_id: D("100") for b in r.balances}
        # Override SACS roles with realistic numbers.
        for account in client.accounts:
            if account.section == AccountSection.SACS_INFLOW:
                by_account[account.id] = D("15000")
            elif account.section == AccountSection.SACS_OUTFLOW:
                by_account[account.id] = D("12000")
            elif account.section == AccountSection.SACS_PRIVATE_RESERVE:
                by_account[account.id] = D("75000")
            elif account.section == AccountSection.SACS_INVESTMENT:
                by_account[account.id] = D("15000")
            elif (
                account.section == AccountSection.RETIREMENT
                and account.owner == AccountOwner.CLIENT1
            ):
                by_account[account.id] = D("11162.47")
            elif (
                account.section == AccountSection.RETIREMENT
                and account.owner == AccountOwner.CLIENT2
            ):
                by_account[account.id] = D("126160.38")
            elif account.section == AccountSection.NON_RETIREMENT:
                by_account[account.id] = D("50000")
            elif account.section == AccountSection.TRUST:
                by_account[account.id] = D("450000")

        by_liab = {lb.liability_id: D("100000") for lb in r.liability_balances}

        totals = compute_totals(client, by_account, by_liab)

        assert totals.inflow == D("15000")
        assert totals.outflow == D("12000")
        assert totals.excess == D("3000.00")
        # 6 * 12000 + 1000 + 2000 = 75000
        assert totals.pr_target == D("75000.00")
        assert totals.c1_retirement == D("11162.47")
        assert totals.c2_retirement == D("126160.38")
        assert totals.non_retirement == D("50000.00")
        assert totals.trust_value == D("450000.00")
        assert totals.grand_total == D("637322.85")  # sum of 4 boxes
        assert totals.liabilities_total == D("200000.00")


def test_compute_totals_falls_back_to_static_inflow_outflow(app, rich_client):
    """If no SACS balances entered, fall back to salaries + expense budget."""
    with app.app_context():
        client = db.session.get(Client, rich_client)
        totals = compute_totals(client, {}, {})
        # Salaries sum: 8000 + 7000 = 15000
        assert totals.inflow == D("15000")
        # Expense budget
        assert totals.outflow == D("12000")


# ---- apply_form_to_balances -----------------------------------------------


def test_apply_form_persists_all_fields(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)
        r = scaffold_new_report(client, date.today(), uid)
        db.session.commit()

        form = {}
        for account in client.accounts:
            form[f"balance_{account.id}"] = "1234.56"
            form[f"as_of_{account.id}"] = "2026-01-15"
            if account.section == AccountSection.RETIREMENT:
                form[f"cash_{account.id}"] = "100"
                form[f"stale_{account.id}"] = "on"
        for lb in r.liability_balances:
            form[f"liab_balance_{lb.liability_id}"] = "50000"
            form[f"liab_as_of_{lb.liability_id}"] = "2026-01-15"

        errors = apply_form_to_balances(r, form)
        assert errors == []
        db.session.commit()

        r = db.session.get(Report, r.id)
        for b in r.balances:
            assert b.balance == D("1234.56")
            assert b.as_of_date == date(2026, 1, 15)
        stale = [b for b in r.balances if b.is_stale]
        assert len(stale) == 2  # both retirement accounts
        for lb in r.liability_balances:
            assert lb.balance == D("50000")


# ---- HTTP routes ----------------------------------------------------------


def test_new_report_creates_draft(logged_in_client, app, rich_client):
    resp = logged_in_client.post(
        f"/reports/new/{rich_client}",
        data={"meeting_date": "2026-01-15"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        r = db.session.execute(db.select(Report)).scalar_one()
        assert r.status == ReportStatus.DRAFT
        assert r.meeting_date == date(2026, 1, 15)


def test_duplicate_meeting_date_rejected(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    resp = logged_in_client.post(
        f"/reports/new/{rich_client}",
        data={"meeting_date": "2026-01-15"},
    )
    assert resp.status_code == 200
    assert b"already exists" in resp.data


def test_finalize_locks_report(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()

    logged_in_client.post(f"/reports/{rid}/finalize")
    with app.app_context():
        r = db.session.get(Report, rid)
        assert r.status == ReportStatus.FINAL
        assert r.generated_at is not None


def test_finalized_report_rejects_edits(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()
    logged_in_client.post(f"/reports/{rid}/finalize")

    with app.app_context():
        r = db.session.get(Report, rid)
        first_aid = r.balances[0].account_id
        original_balance = r.balances[0].balance

    logged_in_client.post(f"/reports/{rid}", data={f"balance_{first_aid}": "99999"})

    with app.app_context():
        r = db.session.get(Report, rid)
        assert r.balances[0].balance == original_balance


def test_reopen_returns_to_draft(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()
    logged_in_client.post(f"/reports/{rid}/finalize")
    logged_in_client.post(f"/reports/{rid}/reopen")
    with app.app_context():
        assert db.session.get(Report, rid).status == ReportStatus.DRAFT


def test_live_totals_endpoint_returns_json(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()
        r = db.session.get(Report, rid)
        aid_inflow = next(
            b.account_id for b in r.balances if b.account.section == AccountSection.SACS_INFLOW
        )

    resp = logged_in_client.post(
        f"/reports/{rid}/live-totals",
        data={f"balance_{aid_inflow}": "20000"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["inflow"] == "20000.00"


def test_delete_draft_removes_it(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()
    logged_in_client.post(f"/reports/{rid}/delete")
    with app.app_context():
        assert db.session.get(Report, rid) is None


def test_delete_final_report_refused(logged_in_client, app, rich_client):
    logged_in_client.post(f"/reports/new/{rich_client}", data={"meeting_date": "2026-01-15"})
    with app.app_context():
        rid = db.session.execute(db.select(Report.id)).scalar_one()
    logged_in_client.post(f"/reports/{rid}/finalize")
    logged_in_client.post(f"/reports/{rid}/delete")
    with app.app_context():
        assert db.session.get(Report, rid) is not None


# ---- Entry context building ----------------------------------------------


def test_build_entry_context_sorts_into_buckets(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)
        r = scaffold_new_report(client, date.today(), uid)
        db.session.commit()

        ctx = build_entry_context(r)
        assert "inflow" in ctx.sacs_rows
        assert "outflow" in ctx.sacs_rows
        assert "private_reserve" in ctx.sacs_rows
        assert "investment" in ctx.sacs_rows
        assert len(ctx.c1_retirement) == 1
        assert len(ctx.c2_retirement) == 1
        assert len(ctx.non_retirement) == 1
        assert len(ctx.trust) == 1
        assert len(ctx.liabilities) == 2


def test_totals_from_report_matches_compute_totals(app, rich_client):
    uid = _get_user_id(app)
    with app.app_context():
        client = db.session.get(Client, rich_client)
        r = scaffold_new_report(client, date.today(), uid)
        db.session.commit()
        for b in r.balances:
            b.balance = D("1000")
        for lb in r.liability_balances:
            lb.balance = D("50000")
        db.session.commit()

        t = totals_from_report(r)
        # 1 non-retirement account of $1000
        assert t.non_retirement == D("1000")
        # 2 liabilities of $50000
        assert t.liabilities_total == D("100000")
