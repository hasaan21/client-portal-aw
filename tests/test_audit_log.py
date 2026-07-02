"""Audit-log viewer tests (M7)."""

from __future__ import annotations

from app.extensions import db
from app.models import AuditLog

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
}


def test_audit_log_requires_login(client):
    resp = client.get("/audit")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_audit_log_empty_state(logged_in_client):
    resp = logged_in_client.get("/audit")
    assert resp.status_code == 200
    assert b"No audit entries" in resp.data


def test_audit_log_shows_recent_writes(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    resp = logged_in_client.get("/audit")
    body = resp.data.decode()
    assert "client" in body  # entity chip
    assert "create" in body  # action
    assert "The Smiths" in body  # entered as diff key/value


def test_audit_log_filter_by_entity(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    resp = logged_in_client.get("/audit?entity=client")
    assert resp.status_code == 200
    assert b'value="client" selected' in resp.data

    resp2 = logged_in_client.get("/audit?entity=report")
    assert b"No audit entries" in resp2.data


def test_audit_log_filter_by_action(logged_in_client, app):
    logged_in_client.post("/clients/new", data=VALID_HOUSEHOLD, follow_redirects=True)
    resp = logged_in_client.get("/audit?action=create")
    body = resp.data.decode()
    assert 'value="create" selected' in body


def test_audit_log_respects_limit(logged_in_client, app):
    # Insert 5 dummy entries
    with app.app_context():
        for i in range(5):
            db.session.add(AuditLog(entity="test", entity_id=i, action="create"))
        db.session.commit()

    resp = logged_in_client.get("/audit?entity=test&limit=3")
    body = resp.data.decode()
    # Only 3 rows in the table body
    assert body.count("<tr>") == 4  # 1 header + 3 data rows


def test_audit_nav_link_present(logged_in_client):
    resp = logged_in_client.get("/")
    assert b'href="/audit"' in resp.data
