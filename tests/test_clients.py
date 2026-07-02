"""Client CRUD tests (M2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import (
    Account,
    AccountKind,
    AccountOwner,
    AccountSection,
    AuditLog,
    Client,
    InsuranceDeductible,
    Liability,
    LiabilityKind,
)

VALID_HOUSEHOLD = {
    "household_label": "The Smiths",
    "c1_first": "John",
    "c1_last": "Smith",
    "c1_dob": "1970-05-14",
    "c1_ssn_last4": "1234",
    "c1_monthly_salary": "12000.00",
    "monthly_expense_budget": "8000.00",
    "private_reserve_label": "PRIVATE RESERVE",
    "trust_label": "Smith Family Trust",
    "trust_property_address": "123 Main St, Austin, TX",
}


# ---- List ------------------------------------------------------------------


def test_list_empty_state(logged_in_client):
    resp = logged_in_client.get("/clients/")
    assert resp.status_code == 200
    assert b"No clients yet" in resp.data


def test_list_shows_created_client(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    resp = logged_in_client.get("/clients/")
    assert b"The Smiths" in resp.data
    assert b"John Smith" in resp.data


# ---- Create ---------------------------------------------------------------


def test_create_married_household(logged_in_client, app):
    data = {
        **VALID_HOUSEHOLD,
        "c2_first": "Jane",
        "c2_last": "Smith",
        "c2_dob": "1972-03-22",
        "c2_ssn_last4": "5678",
        "c2_monthly_salary": "3000.00",
    }
    resp = logged_in_client.post("/clients/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        client = db.session.execute(db.select(Client)).scalar_one()
        assert client.is_married
        assert client.c2_first == "Jane"
        assert client.c1_age is not None


def test_create_partial_client2_rejected(logged_in_client):
    """If any Client-2 field is set, first + last + DOB are required."""
    data = {**VALID_HOUSEHOLD, "c2_first": "Jane"}
    resp = logged_in_client.post("/clients/new", data=data)
    assert resp.status_code == 200  # re-renders form
    assert b"is required when any Client 2" in resp.data


def test_create_invalid_ssn(logged_in_client):
    resp = logged_in_client.post(
        "/clients/new",
        data={**VALID_HOUSEHOLD, "c1_ssn_last4": "12"},
    )
    assert resp.status_code == 200
    assert b"last 4 digits" in resp.data


def test_create_writes_audit(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    with app.app_context():
        entries = db.session.execute(db.select(AuditLog).filter_by(entity="client")).scalars().all()
        assert len(entries) == 1
        assert entries[0].action == "create"


# ---- Edit -----------------------------------------------------------------


def test_edit_updates_and_audits(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    with app.app_context():
        client = db.session.execute(db.select(Client)).scalar_one()
        cid = client.id

    resp = logged_in_client.post(
        f"/clients/{cid}/edit",
        data={**VALID_HOUSEHOLD, "household_label": "The Smith-Joneses"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        client = db.session.get(Client, cid)
        assert client.household_label == "The Smith-Joneses"
        entries = (
            db.session.execute(db.select(AuditLog).filter_by(entity="client", action="update"))
            .scalars()
            .all()
        )
        assert len(entries) == 1


# ---- Archive / restore -----------------------------------------------------


def test_archive_and_restore(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    with app.app_context():
        cid = db.session.execute(db.select(Client.id)).scalar_one()

    logged_in_client.post(f"/clients/{cid}/archive", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Client, cid).archived_at is not None

    # Archived clients are hidden from default list.
    resp = logged_in_client.get("/clients/")
    assert b"The Smiths" not in resp.data
    resp_archived = logged_in_client.get("/clients/?archived=1")
    assert b"The Smiths" in resp_archived.data

    logged_in_client.post(f"/clients/{cid}/restore", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Client, cid).archived_at is None


# ---- Accounts --------------------------------------------------------------


def _make_client(app) -> int:
    with app.app_context():
        c = Client(
            household_label="Test HH",
            c1_first="A",
            c1_last="B",
            c1_dob=date(1980, 1, 1),
            c1_ssn_last4="1111",
            c1_monthly_salary=Decimal("10000"),
            monthly_expense_budget=Decimal("5000"),
        )
        db.session.add(c)
        db.session.commit()
        return c.id


def test_add_account_ok(logged_in_client, app):
    cid = _make_client(app)
    resp = logged_in_client.post(
        f"/clients/{cid}/accounts/new",
        data={
            "section": AccountSection.RETIREMENT.value,
            "owner": AccountOwner.CLIENT1.value,
            "kind": AccountKind.ROTH_IRA.value,
            "display_name": "Fidelity Roth",
            "last4": "9876",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        acct = db.session.execute(db.select(Account)).scalar_one()
        assert acct.section == AccountSection.RETIREMENT
        assert acct.owner == AccountOwner.CLIENT1


def test_retirement_joint_rejected(logged_in_client, app):
    cid = _make_client(app)
    resp = logged_in_client.post(
        f"/clients/{cid}/accounts/new",
        data={
            "section": AccountSection.RETIREMENT.value,
            "owner": AccountOwner.JOINT.value,
            "kind": AccountKind.IRA.value,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        count = db.session.execute(db.select(db.func.count()).select_from(Account)).scalar_one()
        assert count == 0


def test_delete_account(logged_in_client, app):
    cid = _make_client(app)
    logged_in_client.post(
        f"/clients/{cid}/accounts/new",
        data={
            "section": AccountSection.NON_RETIREMENT.value,
            "owner": AccountOwner.JOINT.value,
            "kind": AccountKind.CHECKING.value,
        },
    )
    with app.app_context():
        aid = db.session.execute(db.select(Account.id)).scalar_one()
    logged_in_client.post(f"/clients/{cid}/accounts/{aid}/delete", follow_redirects=True)
    with app.app_context():
        count = db.session.execute(db.select(db.func.count()).select_from(Account)).scalar_one()
        assert count == 0


# ---- Liabilities & deductibles --------------------------------------------


def test_add_liability(logged_in_client, app):
    cid = _make_client(app)
    logged_in_client.post(
        f"/clients/{cid}/liabilities/new",
        data={
            "kind": LiabilityKind.MORTGAGE.value,
            "label": "P Mortg",
            "interest_rate": "6.125",
        },
        follow_redirects=True,
    )
    with app.app_context():
        lb = db.session.execute(db.select(Liability)).scalar_one()
        assert lb.label == "P Mortg"
        assert lb.interest_rate == Decimal("6.125")


def test_add_deductible(logged_in_client, app):
    cid = _make_client(app)
    logged_in_client.post(
        f"/clients/{cid}/deductibles/new",
        data={"label": "Health", "amount": "1500"},
        follow_redirects=True,
    )
    with app.app_context():
        d = db.session.execute(db.select(InsuranceDeductible)).scalar_one()
        assert d.amount == Decimal("1500")
