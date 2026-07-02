"""Report history + filtering tests (M6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Client, ReportStatus
from app.reports.services import scaffold_new_report


@pytest.fixture()
def two_clients_with_reports(app, user_factory):
    u = user_factory(email="andrew@example.com")
    with app.app_context():
        smith = Client(
            household_label="Smiths",
            c1_first="John",
            c1_last="Smith",
            c1_dob=date(1970, 1, 1),
            c1_ssn_last4="1111",
            c1_monthly_salary=Decimal("8000"),
            monthly_expense_budget=Decimal("6000"),
        )
        jones = Client(
            household_label="Joneses",
            c1_first="Amy",
            c1_last="Jones",
            c1_dob=date(1975, 5, 5),
            c1_ssn_last4="2222",
            c1_monthly_salary=Decimal("9000"),
            monthly_expense_budget=Decimal("7000"),
        )
        db.session.add_all([smith, jones])
        db.session.commit()

        r1 = scaffold_new_report(smith, date(2026, 1, 15), u.id)
        r2 = scaffold_new_report(smith, date(2026, 4, 15), u.id)
        r3 = scaffold_new_report(jones, date(2026, 1, 15), u.id)
        db.session.commit()
        r1.status = ReportStatus.FINAL
        r2.status = ReportStatus.DRAFT
        r3.status = ReportStatus.FINAL
        db.session.commit()

        return {"smith": smith.id, "jones": jones.id, "r1": r1.id, "r2": r2.id, "r3": r3.id}


# ---- Dashboard -------------------------------------------------------------


def test_dashboard_shows_all_stats(logged_in_client, two_clients_with_reports):
    resp = logged_in_client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Active clients" in body
    assert "Finalized reports" in body
    assert "Open drafts" in body
    # 2 active clients, 2 final, 1 draft
    assert ">2</span>" in body


def test_dashboard_shows_recent_reports(logged_in_client, two_clients_with_reports):
    resp = logged_in_client.get("/")
    body = resp.data.decode()
    assert "Smiths" in body
    assert "Joneses" in body


# ---- Reports index filtering ----------------------------------------------


def test_reports_index_lists_all_when_unfiltered(logged_in_client, two_clients_with_reports):
    resp = logged_in_client.get("/reports/")
    body = resp.data.decode()
    assert "Smiths" in body
    assert "Joneses" in body


def test_reports_index_filter_by_status(logged_in_client, two_clients_with_reports):
    resp = logged_in_client.get("/reports/?status=DRAFT")
    body = resp.data.decode()
    # Only Smith's April draft matches
    assert "Apr 15, 2026" in body
    # Neither final report should appear as a row
    assert body.count("badge--final") == 0


def test_reports_index_filter_by_client(logged_in_client, two_clients_with_reports):
    smith_id = two_clients_with_reports["smith"]
    resp = logged_in_client.get(f"/reports/?client_id={smith_id}")
    body = resp.data.decode()
    # Only Smith rows should appear in the results table.
    # The dropdown list still shows Joneses, so we count how many times each
    # appears as a strong link (i.e. a table row).
    assert body.count('class="link-strong">Smiths</a>') == 2
    assert 'class="link-strong">Joneses</a>' not in body


def test_reports_index_combined_filters(logged_in_client, two_clients_with_reports):
    smith_id = two_clients_with_reports["smith"]
    resp = logged_in_client.get(f"/reports/?client_id={smith_id}&status=FINAL")
    body = resp.data.decode()
    assert "Jan 15, 2026" in body
    assert "Apr 15, 2026" not in body


def test_reports_index_no_matches_shows_empty_state(logged_in_client, two_clients_with_reports):
    # Filter for an impossible combination.
    resp = logged_in_client.get("/reports/?status=DRAFT&client_id=99999")
    body = resp.data.decode()
    assert "No reports match" in body


# ---- Client history --------------------------------------------------------


def test_client_detail_shows_report_history(logged_in_client, two_clients_with_reports):
    smith_id = two_clients_with_reports["smith"]
    resp = logged_in_client.get(f"/clients/{smith_id}")
    body = resp.data.decode()
    # Both Smith reports should appear
    assert "Jan 15, 2026" in body
    assert "Apr 15, 2026" in body
