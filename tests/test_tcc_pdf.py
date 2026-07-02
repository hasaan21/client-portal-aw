"""TCC PDF snapshot tests.

Validates content presence, page count, and Rebecca's key invariants:
- Liabilities never subtracted from Grand Total.
- Trust never added to Non-Retirement subtotal.
- Stale balances show '*' and produce a footnote.
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
from app.pdf.tcc import render_tcc
from app.reports.services import scaffold_new_report

D = Decimal


@pytest.fixture()
def tcc_ready_report(app, user_factory):
    """Mirrors the Sample Client — Green screenshot as closely as possible."""
    u = user_factory(email="andrew@example.com")
    with app.app_context():
        c = Client(
            household_label="Green Family",
            c1_first="John",
            c1_last="Green",
            c1_dob=date(1970, 5, 14),
            c1_ssn_last4="1234",
            c1_monthly_salary=D("8000"),
            c2_first="Jane",
            c2_last="Green",
            c2_dob=date(1972, 3, 22),
            c2_ssn_last4="5678",
            c2_monthly_salary=D("7000"),
            monthly_expense_budget=D("12000"),
            private_reserve_label="PRIVATE RESERVE",
            trust_label="Green Family Trust",
            trust_property_address="123 Main St, Austin, TX",
        )
        db.session.add(c)
        db.session.flush()

        # Retirement per side (matches the sample layout)
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT1,
                kind=AccountKind.ROTH_IRA,
                display_name="Fidelity Roth",
                custodian="Fidelity",
                last4="1122",
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT1,
                kind=AccountKind.IRA,
                display_name="Vanguard IRA",
                custodian="Vanguard",
                last4="3344",
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT2,
                kind=AccountKind._401K,
                display_name="Schwab 401(k)",
                custodian="Schwab",
                last4="5566",
            )
        )
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT2,
                kind=AccountKind.PENSION,
                display_name="Company Pension",
                custodian="Empower",
                last4="7788",
            )
        )

        # Non-retirement (single joint account for simplicity)
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.NON_RETIREMENT,
                owner=AccountOwner.JOINT,
                kind=AccountKind.CHECKING,
                display_name="Wells Fargo Main",
                custodian="Wells Fargo",
                last4="9900",
            )
        )

        # Trust
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.TRUST,
                owner=AccountOwner.TRUST,
                kind=AccountKind.OTHER,
                display_name="Trust Property",
            )
        )

        # Liabilities (matches sample)
        db.session.add(
            Liability(
                client_id=c.id,
                kind=LiabilityKind.MORTGAGE,
                label="P Mortg",
                interest_rate=D("6.125"),
            )
        )
        db.session.add(
            Liability(
                client_id=c.id, kind=LiabilityKind.AUTO, label="Mercedes", interest_rate=D("4.500")
            )
        )

        db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
        db.session.commit()

        report = scaffold_new_report(c, date(2026, 1, 15), u.id)
        db.session.commit()

        # Populate balances from the sample screenshot
        for b in report.balances:
            if (
                b.account.section == AccountSection.RETIREMENT
                and b.account.owner == AccountOwner.CLIENT1
            ):
                b.balance = (
                    D("11162.47") if "Roth" in (b.account.display_name or "") else D("15000")
                )
            elif (
                b.account.section == AccountSection.RETIREMENT
                and b.account.owner == AccountOwner.CLIENT2
            ):
                b.balance = (
                    D("70042.00") if "401" in (b.account.display_name or "") else D("56118.38")
                )
            elif b.account.section == AccountSection.NON_RETIREMENT:
                b.balance = D("189308.04")
            elif b.account.section == AccountSection.TRUST:
                b.balance = D("450000")
        for lb in report.liability_balances:
            liab = next(x for x in report.client.liabilities if x.id == lb.liability_id)
            if liab.label == "P Mortg":
                lb.balance = D("224218.24")
            elif liab.label == "Mercedes":
                lb.balance = D("11152.00")
        db.session.commit()
        return report.id


def _extract(app, report_id: int) -> tuple[bytes, str, int]:
    with app.app_context():
        report = db.session.get(Report, report_id)
        data = render_tcc(report)
    text = extract_text(BytesIO(data))
    with BytesIO(data) as fh:
        pages = list(PDFPage.get_pages(fh))
    return data, text, len(pages)


def test_tcc_produces_valid_pdf(app, tcc_ready_report):
    data, _, pages = _extract(app, tcc_ready_report)
    assert data.startswith(b"%PDF-")
    assert pages == 1


def test_tcc_header_content(app, tcc_ready_report):
    _, text, _ = _extract(app, tcc_ready_report)
    assert "Green Family" in text
    assert "January 15, 2026" in text
    assert "GRAND TOTAL" in text


def test_tcc_shows_retirement_account_labels(app, tcc_ready_report):
    """Retirement accounts render as individual bubbles per spouse.

    Non-retirement is also itemized as individual bubbles (matching the
    reference sample); liabilities are itemized in the center table.
    Labels are truncated to ~14 chars in the small bubbles, so we check for
    substrings rather than exact matches.
    """
    _, text, _ = _extract(app, tcc_ready_report)
    for label in ["Fidelity Roth", "Vanguard IRA", "Company Pension"]:
        assert label in text, f"Missing retirement account: {label}"
    # "Schwab 401(k)" is 14 chars — may be truncated to "Schwab 401(k…" depending on layout
    assert "Schwab" in text


def test_tcc_shows_computed_grand_total(app, tcc_ready_report):
    """Grand total = C1 retirement + C2 retirement + non-retirement + trust."""
    _, text, _ = _extract(app, tcc_ready_report)
    # 11162.47 + 15000 + 70042 + 56118.38 + 189308.04 + 450000 = 791630.89
    assert "GRAND TOTAL" in text
    assert "$791,630.89" in text


def test_tcc_shows_non_retirement_subtotal(app, tcc_ready_report):
    _, text, _ = _extract(app, tcc_ready_report)
    assert "NON RETIREMENT TOTAL" in text
    assert "$189,308.04" in text


def test_tcc_liabilities_section(app, tcc_ready_report):
    _, text, _ = _extract(app, tcc_ready_report)
    assert "Liabilities" in text
    assert "P Mortg" in text
    assert "Mercedes" in text
    assert "$224,218.24" in text
    assert "$11,152.00" in text
    # Total liabilities: 224218.24 + 11152 = 235370.24 — NOT subtracted from grand total
    assert "$235,370.24" in text


def test_tcc_liabilities_never_subtracted_from_grand_total(app, tcc_ready_report):
    """Explicit test of Rebecca's critical rule."""
    _, text, _ = _extract(app, tcc_ready_report)
    # Grand total minus liabilities would be 791630.89 - 235370.24 = 556260.65.
    # That number must NOT appear on the PDF anywhere.
    assert "$556,260.65" not in text


def test_tcc_trust_not_added_to_non_retirement(app, tcc_ready_report):
    """189,308 (non-ret) + 450,000 (trust) would be 639,308 — must not appear."""
    _, text, _ = _extract(app, tcc_ready_report)
    assert "$639,308" not in text
    assert "$189,308.04" in text  # non-retirement subtotal unchanged
    assert "$450,000" in text  # trust standalone


def test_tcc_stale_footnote_and_asterisk(app, tcc_ready_report):
    """Setting a balance stale must add '*' + a footnote to the PDF."""
    with app.app_context():
        report = db.session.get(Report, tcc_ready_report)
        for b in report.balances:
            if b.account.section == AccountSection.RETIREMENT:
                b.is_stale = True
                break
        db.session.commit()

    _, text, _ = _extract(app, tcc_ready_report)
    assert "*" in text
    assert "up to date information" in text


def test_tcc_no_stale_footnote_when_all_current(app, tcc_ready_report):
    _, text, _ = _extract(app, tcc_ready_report)
    assert "up to date information" not in text


def test_tcc_deterministic(app, tcc_ready_report):
    _, a, _ = _extract(app, tcc_ready_report)
    _, b, _ = _extract(app, tcc_ready_report)
    assert a == b


def test_tcc_writes_to_disk(app, tcc_ready_report, tmp_path):
    with app.app_context():
        report = db.session.get(Report, tcc_ready_report)
        out = tmp_path / "tcc.pdf"
        render_tcc(report, out)
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF-")


def test_finalize_generates_both_pdfs(logged_in_client, app, tcc_ready_report):
    logged_in_client.post(f"/reports/{tcc_ready_report}/finalize")
    with app.app_context():
        report = db.session.get(Report, tcc_ready_report)
        assert report.sacs_pdf_path is not None
        assert report.tcc_pdf_path is not None

    resp = logged_in_client.get(f"/reports/{tcc_ready_report}/pdf/tcc")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_tcc_shows_single_client_when_unmarried(app, user_factory):
    u = user_factory(email="a@example.com")
    with app.app_context():
        c = Client(
            household_label="Solo Client",
            c1_first="Alex",
            c1_last="Doe",
            c1_dob=date(1985, 1, 1),
            c1_ssn_last4="0000",
            c1_monthly_salary=D("6000"),
            monthly_expense_budget=D("4000"),
        )
        db.session.add(c)
        db.session.flush()
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=AccountOwner.CLIENT1,
                kind=AccountKind.IRA,
            )
        )
        db.session.commit()
        r = scaffold_new_report(c, date(2026, 1, 15), u.id)
        db.session.commit()
        rid = r.id

    with app.app_context():
        report = db.session.get(Report, rid)
        data = render_tcc(report)
    text = extract_text(BytesIO(data))
    assert "Alex" in text
    assert "Solo Client" in text
    # Client 2 name oval should NOT be rendered for a single-client household
    assert "Client 2 Retirement Only" not in text
