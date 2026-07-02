"""Report business logic: totals computation, previous-quarter lookup,
balance persistence.

Everything here is deterministic and side-effect-scoped to a single Report row;
route handlers are thin wrappers around these functions so they can be unit
tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.calc.engine import (
    excess,
    grand_total_net_worth,
    liabilities_total,
    non_retirement_total,
    pr_target,
    retirement_totals,
    round_money,
)
from app.extensions import db
from app.models import (
    Account,
    AccountOwner,
    AccountSection,
    Balance,
    Client,
    Liability,
    LiabilityBalance,
    Report,
    ReportStatus,
)

ZERO = Decimal("0.00")


# ------------------------------------------------------------------ totals --


@dataclass
class ReportTotals:
    """Everything the SACS + TCC PDFs (and the live UI) need in one place."""

    inflow: Decimal = ZERO
    outflow: Decimal = ZERO
    excess: Decimal = ZERO
    pr_balance: Decimal = ZERO
    pr_target: Decimal = ZERO
    investment_balance: Decimal = ZERO
    c1_retirement: Decimal = ZERO
    c2_retirement: Decimal = ZERO
    non_retirement: Decimal = ZERO
    trust_value: Decimal = ZERO
    grand_total: Decimal = ZERO
    liabilities_total: Decimal = ZERO
    stale_present: bool = False

    def as_dict(self) -> dict[str, str]:
        """JSON-safe serialization for the live-totals endpoint."""
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


def _decimal_or_zero(raw: str | float | Decimal | None) -> Decimal:
    if raw in (None, ""):
        return ZERO
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return ZERO


def compute_totals(
    client: Client,
    balances_by_account: dict[int, Decimal],
    liability_balances: dict[int, Decimal],
    stale_flags: dict[int, bool] | None = None,
) -> ReportTotals:
    """Group balances by section/owner and run every PRD formula.

    ``balances_by_account`` is keyed by Account.id.
    ``liability_balances`` is keyed by Liability.id.
    ``stale_flags`` is keyed by Account.id (subset that are stale).
    """
    stale_flags = stale_flags or {}
    totals = ReportTotals()

    c1_ret: list[Decimal] = []
    c2_ret: list[Decimal] = []
    non_ret: list[Decimal] = []

    for account in client.accounts:
        balance = _decimal_or_zero(balances_by_account.get(account.id))
        if stale_flags.get(account.id):
            totals.stale_present = True

        if account.section == AccountSection.SACS_INFLOW:
            totals.inflow += balance
        elif account.section == AccountSection.SACS_OUTFLOW:
            totals.outflow += balance
        elif account.section == AccountSection.SACS_PRIVATE_RESERVE:
            totals.pr_balance += balance
        elif account.section == AccountSection.SACS_INVESTMENT:
            totals.investment_balance += balance
        elif account.section == AccountSection.RETIREMENT:
            if account.owner == AccountOwner.CLIENT1:
                c1_ret.append(balance)
            elif account.owner == AccountOwner.CLIENT2:
                c2_ret.append(balance)
        elif account.section == AccountSection.NON_RETIREMENT:
            non_ret.append(balance)
        elif account.section == AccountSection.TRUST:
            totals.trust_value += balance

    # If the SACS inflow account balance wasn't entered, fall back to the
    # client's static take-home salary (per Data Point List: "Inflow = Client
    # Salary"). Same for outflow: fall back to the agreed monthly expense.
    if totals.inflow == ZERO:
        totals.inflow = (client.c1_monthly_salary or ZERO) + (client.c2_monthly_salary or ZERO)
    if totals.outflow == ZERO:
        totals.outflow = client.monthly_expense_budget or ZERO

    totals.excess = excess(totals.inflow, totals.outflow)

    deductibles = [d.amount for d in client.deductibles]
    if client.private_reserve_target_override is not None:
        totals.pr_target = client.private_reserve_target_override
    else:
        totals.pr_target = pr_target(client.monthly_expense_budget or ZERO, deductibles)

    totals.c1_retirement, totals.c2_retirement = retirement_totals(c1_ret, c2_ret)
    totals.non_retirement = non_retirement_total(non_ret)
    totals.grand_total = grand_total_net_worth(
        totals.c1_retirement, totals.c2_retirement, totals.non_retirement, totals.trust_value
    )
    totals.liabilities_total = liabilities_total(liability_balances.values())

    # Normalize accumulator fields to 2dp so JSON serialization is consistent
    # with the calc-engine outputs above.
    totals.inflow = round_money(totals.inflow)
    totals.outflow = round_money(totals.outflow)
    totals.pr_balance = round_money(totals.pr_balance)
    totals.investment_balance = round_money(totals.investment_balance)
    totals.trust_value = round_money(totals.trust_value)

    return totals


def totals_from_report(report: Report) -> ReportTotals:
    """Compute totals from persisted Balance rows."""
    bmap = {b.account_id: b.balance for b in report.balances}
    lmap = {lb.liability_id: lb.balance for lb in report.liability_balances}
    stale = {b.account_id: b.is_stale for b in report.balances if b.is_stale}
    return compute_totals(report.client, bmap, lmap, stale)


# ---------------------------------------------- previous quarter reference --


def previous_final_report(client: Client, before_report: Report) -> Report | None:
    """Most recent FINAL report on the client, strictly earlier than
    ``before_report`` — the source for 'last quarter' hints and 'use last value'
    chips."""
    stmt = (
        db.select(Report)
        .where(Report.client_id == client.id)
        .where(Report.status == ReportStatus.FINAL)
        .where(Report.meeting_date < before_report.meeting_date)
        .order_by(Report.meeting_date.desc())
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def previous_balance(account_id: int, previous_report: Report | None) -> Balance | None:
    if previous_report is None:
        return None
    for b in previous_report.balances:
        if b.account_id == account_id:
            return b
    return None


def previous_liability_balance(
    liability_id: int, previous_report: Report | None
) -> LiabilityBalance | None:
    if previous_report is None:
        return None
    for lb in previous_report.liability_balances:
        if lb.liability_id == liability_id:
            return lb
    return None


# ------------------------------------------------- scaffold + persistence --


def scaffold_new_report(client: Client, meeting_date: date, user_id: int) -> Report:
    """Create a Draft report with a zero Balance row per Account and a zero
    LiabilityBalance row per Liability so the entry form has stable form
    keys."""
    report = Report(
        client_id=client.id,
        created_by_user_id=user_id,
        meeting_date=meeting_date,
        status=ReportStatus.DRAFT,
    )
    db.session.add(report)
    db.session.flush()

    prev = previous_final_report(client, report)

    for account in client.accounts:
        pb = previous_balance(account.id, prev)
        db.session.add(
            Balance(
                report_id=report.id,
                account_id=account.id,
                balance=pb.balance if pb else ZERO,
                cash_balance=pb.cash_balance if pb else None,
                as_of_date=meeting_date,
                is_stale=False,
            )
        )
    for liability in client.liabilities:
        plb = previous_liability_balance(liability.id, prev)
        db.session.add(
            LiabilityBalance(
                report_id=report.id,
                liability_id=liability.id,
                balance=plb.balance if plb else ZERO,
                as_of_date=meeting_date,
            )
        )
    return report


def apply_form_to_balances(report: Report, form_data: dict[str, Any]) -> list[str]:
    """Persist balance edits from a POSTed report-entry form.

    Field naming convention:
    - ``balance_<account_id>``, ``cash_<account_id>``,
      ``as_of_<account_id>``, ``stale_<account_id>``
    - ``liab_balance_<liab_id>``, ``liab_as_of_<liab_id>``

    Returns a list of validation-error strings (empty list = success).
    """
    errors: list[str] = []

    for balance_row in report.balances:
        aid = balance_row.account_id
        raw_balance = form_data.get(f"balance_{aid}", "")
        raw_cash = form_data.get(f"cash_{aid}", "")
        raw_as_of = form_data.get(f"as_of_{aid}", "")
        stale = form_data.get(f"stale_{aid}") in ("on", "true", "1", "yes")

        try:
            balance_row.balance = _decimal_or_zero(raw_balance)
            balance_row.cash_balance = _decimal_or_zero(raw_cash) if raw_cash else None
            balance_row.as_of_date = (
                date.fromisoformat(raw_as_of) if raw_as_of else balance_row.as_of_date
            )
            balance_row.is_stale = bool(stale)
        except ValueError:
            errors.append(f"Invalid input for account #{aid}.")

    for lbrow in report.liability_balances:
        lid = lbrow.liability_id
        raw_balance = form_data.get(f"liab_balance_{lid}", "")
        raw_as_of = form_data.get(f"liab_as_of_{lid}", "")

        try:
            lbrow.balance = _decimal_or_zero(raw_balance)
            lbrow.as_of_date = date.fromisoformat(raw_as_of) if raw_as_of else lbrow.as_of_date
        except ValueError:
            errors.append(f"Invalid input for liability #{lid}.")

    return errors


# --------------------------------------------- form scaffolding for the UI --


@dataclass
class BalanceRow:
    """Everything the UI needs to render a single balance-entry row."""

    account: Account
    balance: Balance
    previous: Balance | None
    section: AccountSection
    owner: AccountOwner
    show_cash: bool = False


@dataclass
class LiabilityRow:
    liability: Liability
    balance: LiabilityBalance
    previous: LiabilityBalance | None


@dataclass
class ReportEntryContext:
    """All data the report-entry template needs, pre-organized by section."""

    report: Report
    client: Client
    previous_report: Report | None
    sacs_rows: dict[str, BalanceRow | None] = field(default_factory=dict)
    c1_retirement: list[BalanceRow] = field(default_factory=list)
    c2_retirement: list[BalanceRow] = field(default_factory=list)
    non_retirement: list[BalanceRow] = field(default_factory=list)
    trust: list[BalanceRow] = field(default_factory=list)
    liabilities: list[LiabilityRow] = field(default_factory=list)


_CASH_SHOWN_KINDS = {"IRA", "ROTH_IRA", "401K", "PENSION", "BROKERAGE", "STOCK_OPTIONS"}


def build_entry_context(report: Report) -> ReportEntryContext:
    """Organize accounts/liabilities into the UI's section buckets."""
    ctx = ReportEntryContext(
        report=report,
        client=report.client,
        previous_report=previous_final_report(report.client, report),
    )

    balance_by_account = {b.account_id: b for b in report.balances}

    for account in report.client.accounts:
        row = BalanceRow(
            account=account,
            balance=balance_by_account.get(account.id)
            or Balance(report_id=report.id, account_id=account.id, balance=ZERO),
            previous=previous_balance(account.id, ctx.previous_report),
            section=account.section,
            owner=account.owner,
            show_cash=account.kind.value in _CASH_SHOWN_KINDS,
        )
        if account.section == AccountSection.SACS_INFLOW:
            ctx.sacs_rows["inflow"] = row
        elif account.section == AccountSection.SACS_OUTFLOW:
            ctx.sacs_rows["outflow"] = row
        elif account.section == AccountSection.SACS_PRIVATE_RESERVE:
            ctx.sacs_rows["private_reserve"] = row
        elif account.section == AccountSection.SACS_INVESTMENT:
            ctx.sacs_rows["investment"] = row
        elif account.section == AccountSection.RETIREMENT:
            if account.owner == AccountOwner.CLIENT1:
                ctx.c1_retirement.append(row)
            elif account.owner == AccountOwner.CLIENT2:
                ctx.c2_retirement.append(row)
        elif account.section == AccountSection.NON_RETIREMENT:
            ctx.non_retirement.append(row)
        elif account.section == AccountSection.TRUST:
            ctx.trust.append(row)

    liability_balance_by_id = {lb.liability_id: lb for lb in report.liability_balances}
    for liab in report.client.liabilities:
        ctx.liabilities.append(
            LiabilityRow(
                liability=liab,
                balance=liability_balance_by_id.get(liab.id)
                or LiabilityBalance(report_id=report.id, liability_id=liab.id, balance=ZERO),
                previous=previous_liability_balance(liab.id, ctx.previous_report),
            )
        )

    return ctx
