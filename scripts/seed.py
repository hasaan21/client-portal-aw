"""Seed the three team users, and optionally a demo client.

Usage:
    python scripts/seed.py                    # users only
    python scripts/seed.py --demo             # users + one demo client with a final report
    python scripts/seed.py --demo --force     # even if the demo client already exists

Idempotent: re-running only updates missing fields, never overwrites hashes.

Passwords are printed to stdout the FIRST time a user is created and then never
again. Save them in your password manager immediately.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
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
    ReportStatus,
    User,
)
from app.pdf.orchestrator import generate_all
from app.reports.services import scaffold_new_report

TEAM = [
    {"email": "andrew@example.com", "name": "Andrew Windbrook", "is_admin": True},
    {"email": "rebecca@example.com", "name": "Rebecca Planner", "is_admin": False},
    {"email": "maryann@example.com", "name": "Maryann Assistant", "is_admin": False},
]

D = Decimal


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def _seed_users() -> tuple[int, User]:
    created = 0
    first_user = None
    for spec in TEAM:
        existing = db.session.execute(
            db.select(User).filter_by(email=spec["email"])
        ).scalar_one_or_none()
        if existing:
            print(f"= exists     {spec['email']}")
            first_user = first_user or existing
            continue

        password = os.environ.get("SEED_ADMIN_PASSWORD") or _generate_password()
        user = User(email=spec["email"], name=spec["name"], is_admin=spec["is_admin"])
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        first_user = first_user or user
        created += 1
        print(f"+ created    {spec['email']:32s}  password: {password}")

    return created, first_user


def _seed_demo_client(admin: User, force: bool) -> None:
    existing = db.session.execute(
        db.select(Client).filter_by(household_label="Demo — Green Household")
    ).scalar_one_or_none()
    if existing and not force:
        print("= demo client already exists (pass --force to recreate)")
        return
    if existing:
        db.session.delete(existing)
        db.session.commit()

    c = Client(
        household_label="Demo — Green Household",
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

    retirement = [
        (AccountOwner.CLIENT1, AccountKind.ROTH_IRA, "Fidelity Roth", "Fidelity", "1122"),
        (AccountOwner.CLIENT1, AccountKind.IRA, "Vanguard IRA", "Vanguard", "3344"),
        (AccountOwner.CLIENT2, AccountKind._401K, "Schwab 401(k)", "Schwab", "5566"),
        (AccountOwner.CLIENT2, AccountKind.PENSION, "Empower Pension", "Empower", "7788"),
    ]
    for owner, kind, name, custodian, last4 in retirement:
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.RETIREMENT,
                owner=owner,
                kind=kind,
                display_name=name,
                custodian=custodian,
                last4=last4,
            )
        )

    db.session.add(
        Account(
            client_id=c.id,
            section=AccountSection.NON_RETIREMENT,
            owner=AccountOwner.JOINT,
            kind=AccountKind.CHECKING,
            display_name="Wells Fargo Main",
            custodian="Wells Fargo",
            last4="9911",
        )
    )
    db.session.add(
        Account(
            client_id=c.id,
            section=AccountSection.TRUST,
            owner=AccountOwner.TRUST,
            kind=AccountKind.OTHER,
            display_name="Trust Property",
        )
    )

    db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
    db.session.add(InsuranceDeductible(client_id=c.id, label="Home", amount=D("2000")))
    db.session.add(
        Liability(
            client_id=c.id, kind=LiabilityKind.MORTGAGE, label="P Mortg", interest_rate=D("6.125")
        )
    )
    db.session.add(
        Liability(
            client_id=c.id, kind=LiabilityKind.AUTO, label="Mercedes", interest_rate=D("4.500")
        )
    )
    db.session.commit()

    # Create one FINAL report so the dashboard doesn't look empty on first boot.
    meeting = date.today() - timedelta(days=30)
    report = scaffold_new_report(c, meeting, admin.id)
    db.session.commit()

    populate = {
        (AccountSection.SACS_INFLOW,): D("15000"),
        (AccountSection.SACS_OUTFLOW,): D("12000"),
        (AccountSection.SACS_PRIVATE_RESERVE,): D("52000"),
        (AccountSection.SACS_INVESTMENT,): D("18500"),
        (AccountSection.NON_RETIREMENT,): D("189308.04"),
        (AccountSection.TRUST,): D("450000"),
    }
    for b in report.balances:
        if (b.account.section,) in populate:
            b.balance = populate[(b.account.section,)]
        elif b.account.section == AccountSection.RETIREMENT:
            name = b.account.display_name or ""
            if "Roth" in name:
                b.balance = D("11162.47")
            elif "IRA" in name:
                b.balance = D("15000")
            elif "401" in name:
                b.balance = D("70042")
            elif "Pension" in name:
                b.balance = D("56118.38")
    for lb in report.liability_balances:
        liab = next(x for x in report.client.liabilities if x.id == lb.liability_id)
        if liab.label == "P Mortg":
            lb.balance = D("224218.24")
        elif liab.label == "Mercedes":
            lb.balance = D("11152.00")

    report.status = ReportStatus.FINAL
    db.session.flush()
    outputs = generate_all(report)
    if "sacs" in outputs:
        report.sacs_pdf_path = outputs["sacs"]
    if "tcc" in outputs:
        report.tcc_pdf_path = outputs["tcc"]
    db.session.commit()

    print(f"+ demo       {c.household_label}  ({len(outputs)} PDFs generated)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed team users + optional demo client.")
    parser.add_argument(
        "--demo", action="store_true", help="Also seed a demo client with a final report."
    )
    parser.add_argument(
        "--force", action="store_true", help="Recreate the demo client if it exists."
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all()
        created, admin = _seed_users()
        if args.demo:
            if admin is None:
                print("! cannot seed demo client without an admin user")
                return 1
            _seed_demo_client(admin, args.force)
        print(f"\n{created} user(s) created; {len(TEAM) - created} already existed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
