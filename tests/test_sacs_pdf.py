"""SACS PDF snapshot tests.

We can't do exact-byte comparison (ReportLab embeds a timestamp and font
subset IDs), so we validate:
  1. Correct number of pages.
  2. Every user-visible string appears in the rendered PDF.
  3. Layout math holds (bytes non-empty, PDF header valid).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from pdfminer.high_level import extract_text
from pdfminer.pdfpage import PDFPage

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
)
from app.pdf.sacs import render_sacs
from app.reports.services import scaffold_new_report

D = Decimal


@pytest.fixture()
def sacs_ready_report(app, user_factory):
    """A married client with realistic SACS numbers and a Draft report ready
    to render."""
    u = user_factory(email="andrew@example.com")
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
            private_reserve_label="PRIVATE RESERVE",
            trust_label="Smith Family Trust",
        )
        db.session.add(c)
        db.session.flush()

        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_INFLOW,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_OUTFLOW,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_PRIVATE_RESERVE,
                owner=AccountOwner.JOINT,
                kind=AccountKind.HYSA,
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.SACS_INVESTMENT,
                owner=AccountOwner.JOINT,
                kind=AccountKind.BROKERAGE,
            )
        )
        db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
        db.session.add(InsuranceDeductible(client_id=c.id, label="Home", amount=D("2000")))
        db.session.commit()

        report = scaffold_new_report(c, date(2026, 1, 15), u.id)
        db.session.commit()

        # Populate SACS balances
        for b in report.balances:
            if b.account.section == AccountSection.SACS_INFLOW:
                b.balance = D("15000")
            elif b.account.section == AccountSection.SACS_OUTFLOW:
                b.balance = D("12000")
            elif b.account.section == AccountSection.SACS_PRIVATE_RESERVE:
                b.balance = D("52000")
            elif b.account.section == AccountSection.SACS_INVESTMENT:
                b.balance = D("18500")
        db.session.commit()
        return report.id


def _extract(app, report_id: int) -> tuple[bytes, str, int]:
    with app.app_context():
        report = db.session.get(Report, report_id)
        data = render_sacs(report)
    text = extract_text(BytesIO(data))
    with BytesIO(data) as fh:
        pages = list(PDFPage.get_pages(fh))
    return data, text, len(pages)


def test_sacs_produces_valid_pdf(app, sacs_ready_report):
    data, _, pages = _extract(app, sacs_ready_report)
    assert data.startswith(b"%PDF-"), "Output is not a valid PDF"
    assert pages == 2, f"Expected 2 pages, got {pages}"


def test_sacs_contains_title_and_client_header(app, sacs_ready_report):
    _, text, _ = _extract(app, sacs_ready_report)
    assert "Simple Automated Cashflow System" in text
    assert "The Smiths" in text
    assert "January 15, 2026" in text


def test_sacs_contains_core_labels(app, sacs_ready_report):
    _, text, _ = _extract(app, sacs_ready_report)
    for label in ["INFLOW", "OUTFLOW", "PRIVATE", "RESERVE", "MONTHLY CASHFLOW"]:
        assert label in text, f"Missing label: {label}"


def test_sacs_page2_contains_investment_and_pr_labels(app, sacs_ready_report):
    _, text, _ = _extract(app, sacs_ready_report)
    assert "INVESTMENT" in text
    assert "ACCOUNT" in text
    assert "Remainder" in text
    assert "6X Monthly Expenses" in text
    # Target is 6 * 12000 + 1000 + 2000 = 75,000
    assert "$75,000.00" in text


def test_sacs_contains_computed_totals(app, sacs_ready_report):
    _, text, _ = _extract(app, sacs_ready_report)
    # Inflow $15,000 / Outflow $12,000 / Excess $3,000 / PR balance $52,000
    assert "$15,000" in text
    assert "$12,000" in text
    assert "$3,000" in text
    assert "$52,000" in text


def test_sacs_uses_configured_private_reserve_label(app, sacs_ready_report):
    """Some clients use 'FICA ACCOUNT' instead of 'PRIVATE RESERVE'."""
    with app.app_context():
        report = db.session.get(Report, sacs_ready_report)
        report.client.private_reserve_label = "FICA ACCOUNT"
        db.session.commit()

    _, text, _ = _extract(app, sacs_ready_report)
    assert "FICA" in text
    assert "ACCOUNT" in text


def test_sacs_writes_to_disk_when_path_given(app, sacs_ready_report, tmp_path):
    with app.app_context():
        report = db.session.get(Report, sacs_ready_report)
        out = tmp_path / "test.pdf"
        render_sacs(report, out)
    assert out.exists()
    assert out.stat().st_size > 500  # non-trivial size
    assert out.read_bytes().startswith(b"%PDF-")


def test_sacs_deterministic_output(app, sacs_ready_report):
    """Same input twice must produce PDFs that agree on user-visible text.

    (Byte-level equality is impossible because of embedded timestamps.)
    """
    _, text_a, _ = _extract(app, sacs_ready_report)
    _, text_b, _ = _extract(app, sacs_ready_report)
    assert text_a == text_b


def test_finalize_endpoint_generates_sacs_pdf(logged_in_client, app, sacs_ready_report):
    logged_in_client.post(f"/reports/{sacs_ready_report}/finalize")
    with app.app_context():
        report = db.session.get(Report, sacs_ready_report)
        assert report.sacs_pdf_path is not None
        assert report.sacs_pdf_path.endswith(".pdf")

    # Download endpoint should serve the file.
    resp = logged_in_client.get(f"/reports/{sacs_ready_report}/pdf/sacs")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data.startswith(b"%PDF-")


def test_download_unknown_kind_404(logged_in_client, sacs_ready_report):
    resp = logged_in_client.get(f"/reports/{sacs_ready_report}/pdf/xls")
    assert resp.status_code == 404


def test_liabilities_never_subtracted_from_display(app, sacs_ready_report):
    """Extra safety: even with huge liabilities, PR balance rendered = raw balance."""
    with app.app_context():
        report = db.session.get(Report, sacs_ready_report)
        # Add a giant liability to make sure it doesn't affect any SACS number.
        c = report.client
        liability = Liability(
            client_id=c.id, kind=LiabilityKind.MORTGAGE, label="Mega", order_idx=0
        )
        db.session.add(liability)
        db.session.flush()
        from app.models import LiabilityBalance

        db.session.add(
            LiabilityBalance(report_id=report.id, liability_id=liability.id, balance=D("999999"))
        )
        db.session.commit()

    _, text, _ = _extract(app, sacs_ready_report)
    # PR balance is $52,000 — should still appear (not $52,000 - $999,999).
    assert "$52,000" in text
