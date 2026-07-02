"""Render sample SACS + TCC PDFs to /tmp for visual review.

Usage:
    python scripts/pdf_preview.py [--client-id N]

If no client is passed, generates a synthetic in-memory client so this can
run on a fresh checkout without needing a seeded DB.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

# Ensure imports work when invoked from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (  # noqa: E402
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
from app.pdf.sacs import render_sacs  # noqa: E402
from app.reports.services import scaffold_new_report  # noqa: E402

D = Decimal


def _make_sample_client() -> tuple[Client, User]:
    admin = User(email="andrew@example.com", name="Andrew")
    admin.set_password("preview-only")
    db.session.add(admin)

    c = Client(
        household_label="Sample Client — Green",
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

    for section, kind in [
        (AccountSection.SACS_INFLOW, AccountKind.CHECKING),
        (AccountSection.SACS_OUTFLOW, AccountKind.CHECKING),
        (AccountSection.SACS_PRIVATE_RESERVE, AccountKind.HYSA),
        (AccountSection.SACS_INVESTMENT, AccountKind.BROKERAGE),
    ]:
        db.session.add(
            Account(client_id=c.id, section=section, owner=AccountOwner.JOINT, kind=kind)
        )

    db.session.add(
        Account(
            client_id=c.id,
            section=AccountSection.RETIREMENT,
            owner=AccountOwner.CLIENT1,
            kind=AccountKind.ROTH_IRA,
            display_name="Fidelity Roth",
        )
    )
    db.session.add(
        Account(
            client_id=c.id,
            section=AccountSection.RETIREMENT,
            owner=AccountOwner.CLIENT2,
            kind=AccountKind._401K,
            display_name="Schwab 401(k)",
        )
    )

    db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
    db.session.add(InsuranceDeductible(client_id=c.id, label="Home", amount=D("2000")))

    db.session.add(
        Liability(
            client_id=c.id, kind=LiabilityKind.MORTGAGE, label="P Mortg", interest_rate=D("6.125")
        )
    )
    db.session.commit()
    return c, admin


def _fill_realistic_balances(report: Report) -> None:
    """Wire in the sample numbers from the reference PDFs."""
    for b in report.balances:
        if b.account.section == AccountSection.SACS_INFLOW:
            b.balance = D("15000")
        elif b.account.section == AccountSection.SACS_OUTFLOW:
            b.balance = D("12000")
        elif b.account.section == AccountSection.SACS_PRIVATE_RESERVE:
            b.balance = D("52000")
        elif b.account.section == AccountSection.SACS_INVESTMENT:
            b.balance = D("18500")
        elif (
            b.account.section == AccountSection.RETIREMENT
            and b.account.owner == AccountOwner.CLIENT1
        ):
            b.balance = D("11162.47")
        elif (
            b.account.section == AccountSection.RETIREMENT
            and b.account.owner == AccountOwner.CLIENT2
        ):
            b.balance = D("126160.38")

    for lb in report.liability_balances:
        lb.balance = D("224218.24")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render sample SACS / TCC PDFs.")
    parser.add_argument(
        "--client-id", type=int, help="Existing client ID to render (uses real DB)."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(tempfile.gettempdir()) / "aw-pdf-preview",
        help="Output directory.",
    )
    args = parser.parse_args()

    app = create_app("testing" if args.client_id is None else None)
    with app.app_context():
        if args.client_id is None:
            # Fresh in-memory DB for a fully synthetic preview.
            db.create_all()
            client, admin = _make_sample_client()
            report = scaffold_new_report(client, date.today(), admin.id)
            db.session.commit()
            _fill_realistic_balances(report)
            report.status = ReportStatus.FINAL
            db.session.commit()
        else:
            report = (
                db.session.execute(db.select(Report).filter_by(client_id=args.client_id))
                .scalars()
                .first()
            )
            if report is None:
                raise SystemExit(f"No report found for client {args.client_id}. Create one first.")

        args.out.mkdir(parents=True, exist_ok=True)
        sacs_path = args.out / "SACS-preview.pdf"
        render_sacs(report, sacs_path)
        print(f"SACS  -> {sacs_path}")

        try:
            from app.pdf.tcc import render_tcc

            tcc_path = args.out / "TCC-preview.pdf"
            render_tcc(report, tcc_path)
            print(f"TCC   -> {tcc_path}")
        except ImportError:
            print("TCC   -> (builder not available yet, ships in M5)")


if __name__ == "__main__":
    main()
