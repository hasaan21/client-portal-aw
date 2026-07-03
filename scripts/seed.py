"""Seed local-dev users and optionally a demo client.

DEV usage:
    python scripts/seed.py                        # users only (local dev)
    python scripts/seed.py --demo                 # users + demo client
    python scripts/seed.py --demo --force         # recreate demo client

PRODUCTION usage:
    python scripts/seed.py --demo --demo-only     # demo client only, no users
    (The initial admin is created by scripts/bootstrap_admin.py from env vars.
     Additional teammates are invited through the /team UI. This script is
     NEVER used to create real production users.)

The TEAM list below intentionally uses `@example.com` placeholders — these
are DEV-ONLY convenience users so the app has something to log in as during
local development. Do not deploy them to production.
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

# Local-dev placeholder team. NEVER shipped to production — production
# bootstraps a single admin via scripts/bootstrap_admin.py using
# BOOTSTRAP_ADMIN_EMAIL, and teammates are invited from the /team UI.
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

    # Retirement — 2 accounts for Client 1 (fills outer + inner left column)
    # and 3 for Client 2 (1 outer-right + 2 stacked inner-right). Matches
    # the reference sample density.
    # Order matters — the TCC PDF puts accounts[:N//2] in the outer column
    # and accounts[N//2:] in the inner column with the remainder stacked.
    # So the first-listed account goes OUTER; put ROTH IRA first for
    # Client 2 to match the reference sample (Roth outer, IRA + 401K inner).
    retirement = [
        (AccountOwner.CLIENT1, AccountKind.ROTH_IRA, "ROTH IRA", "Fidelity", "1122"),
        (AccountOwner.CLIENT1, AccountKind.IRA, "IRA", "Vanguard", "3344"),
        (AccountOwner.CLIENT2, AccountKind.ROTH_IRA, "ROTH IRA", "Fidelity", "9900"),
        (AccountOwner.CLIENT2, AccountKind.IRA, "IRA", "Schwab", "5566"),
        (AccountOwner.CLIENT2, AccountKind._401K, "401K", "Empower", "7788"),
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

    # Non-retirement — 4 on Client 1 side, 3 on Client 2 side.
    non_ret = [
        (
            AccountOwner.JOINT,
            AccountKind.CHECKING,
            "Wells Fargo Main Checking",
            "Wells Fargo",
            "9911",
        ),
        (AccountOwner.JOINT, AccountKind.HYSA, "Wells Fargo Savings", "Wells Fargo", "9912"),
        (AccountOwner.JOINT, AccountKind.HYSA, "StoneCastle FICA", "StoneCastle", "5511"),
        (AccountOwner.JOINT, AccountKind.BROKERAGE, "Schwab JT TEN", "Schwab", "3322"),
        (AccountOwner.CLIENT2, AccountKind.HYSA, "Pinnacle Inflow", "Pinnacle", "7011"),
        (AccountOwner.CLIENT2, AccountKind.HYSA, "Pinnacle Outflow", "Pinnacle", "7012"),
        (AccountOwner.CLIENT2, AccountKind.HYSA, "Pinnacle Private Reserve", "Pinnacle", "7013"),
    ]
    for owner, kind, name, custodian, last4 in non_ret:
        db.session.add(
            Account(
                client_id=c.id,
                section=AccountSection.NON_RETIREMENT,
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
            section=AccountSection.TRUST,
            owner=AccountOwner.TRUST,
            kind=AccountKind.OTHER,
            display_name="Green Family Trust",
        )
    )

    db.session.add(InsuranceDeductible(client_id=c.id, label="Health", amount=D("1000")))
    db.session.add(InsuranceDeductible(client_id=c.id, label="Home", amount=D("2000")))

    # Liabilities — 7 rows so the itemized table matches the reference.
    liabs = [
        (LiabilityKind.MORTGAGE, "P Mortg", D("6.125")),
        (LiabilityKind.MORTGAGE, "S Mortg", D("5.750")),
        (LiabilityKind.AUTO, "Mercedes", D("4.500")),
        (LiabilityKind.AUTO, "GMC Sierra", D("5.250")),
        (LiabilityKind.AUTO, "Escalade", D("6.000")),
        (LiabilityKind.OTHER, "PNC", D("7.250")),
        (LiabilityKind.HEALTH, "Health", D("0.000")),
    ]
    for kind, label, rate in liabs:
        db.session.add(Liability(client_id=c.id, kind=kind, label=label, interest_rate=rate))
    db.session.commit()

    # Create one FINAL report so the dashboard doesn't look empty on first boot.
    meeting = date.today() - timedelta(days=30)
    report = scaffold_new_report(c, meeting, admin.id)
    db.session.commit()

    # SACS balances (single-value sections).
    sacs_balances = {
        AccountSection.SACS_INFLOW: D("15000"),
        AccountSection.SACS_OUTFLOW: D("12000"),
        AccountSection.SACS_PRIVATE_RESERVE: D("52000"),
        AccountSection.SACS_INVESTMENT: D("18500"),
        AccountSection.TRUST: D("0"),
    }
    # Per-account balances (matched by display_name). Values chosen so the
    # non-retirement subtotal matches the reference sample's $189,308.04
    # and cash sub-bubbles show up on retirement accounts that have them.
    retirement_balances = {
        # Client 1
        ("CLIENT1", "ROTH IRA"): (D("11162.47"), D("316")),
        ("CLIENT1", "IRA"): (D("0"), None),
        # Client 2
        ("CLIENT2", "IRA"): (D("37232.46"), D("914")),
        ("CLIENT2", "401K"): (D("70042"), None),
        ("CLIENT2", "ROTH IRA"): (D("18885.92"), D("508")),
    }
    non_ret_balances = {
        "Wells Fargo Main Checking": D("448.26"),
        "Wells Fargo Savings": D("44024"),
        "StoneCastle FICA": D("44067.78"),
        "Schwab JT TEN": D("0"),
        "Pinnacle Inflow": D("990"),
        "Pinnacle Outflow": D("12990"),
        "Pinnacle Private Reserve": D("86788"),
    }
    for b in report.balances:
        section = b.account.section
        if section in sacs_balances:
            b.balance = sacs_balances[section]
        elif section == AccountSection.RETIREMENT:
            key = (b.account.owner.value, b.account.display_name or "")
            if key in retirement_balances:
                bal, cash = retirement_balances[key]
                b.balance = bal
                if cash is not None:
                    b.cash_balance = cash
            # Mark 401K as stale (3 months old) so the red footnote renders
            # on the TCC — matches the reference sample.
            if b.account.display_name == "401K":
                b.is_stale = True
                b.as_of_date = meeting - timedelta(days=92)
        elif section == AccountSection.NON_RETIREMENT:
            b.balance = non_ret_balances.get(b.account.display_name or "", D("0"))
            # Reference sample marks the two Wells Fargo accounts as stale.
            if b.account.display_name in ("Wells Fargo Main Checking", "Wells Fargo Savings"):
                b.is_stale = True
                b.as_of_date = meeting - timedelta(days=40)

    liab_balances = {
        "P Mortg": D("224218.24"),
        "S Mortg": D("107587.31"),
        "Mercedes": D("11152.00"),
        "GMC Sierra": D("25992.00"),
        "Escalade": D("31627.52"),
        "PNC": D("14026.00"),
        "Health": D("1447.00"),
    }
    for lb in report.liability_balances:
        liab = next(x for x in report.client.liabilities if x.id == lb.liability_id)
        lb.balance = liab_balances.get(liab.label, D("0"))

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
        "--demo-only",
        action="store_true",
        help="Skip user seeding entirely (production first-boot demo). Requires "
        "at least one existing user to author the demo report.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Recreate the demo client if it exists."
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all()

        if args.demo_only:
            # Production path: any admin user is fine as the demo report's author.
            admin = db.session.execute(
                db.select(User).order_by(User.is_admin.desc(), User.id).limit(1)
            ).scalar_one_or_none()
            created = 0
        else:
            created, admin = _seed_users()

        if args.demo or args.demo_only:
            if admin is None:
                print("! cannot seed demo client — no user exists to author the report")
                return 1
            _seed_demo_client(admin, args.force)

        if not args.demo_only:
            print(f"\n{created} user(s) created; {len(TEAM) - created} already existed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
