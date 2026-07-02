"""Pure-function calculation engine.

Every formula the PRD calls out lives here. Kept side-effect-free so it can be
unit-tested exhaustively and reused by both the API layer (live totals) and the
PDF layer (final rendering) without divergence.

Rules (from Rebecca's transcript):
- Excess = Inflow - Outflow  (SACS blue-arrow amount)
- PR Target = 6 * monthly_expenses + sum(insurance_deductibles)
- Retirement totals split per spouse (never joint)
- Non-retirement total EXCLUDES the trust (24:28)
- Grand total = C1 retirement + C2 retirement + non-retirement + trust
- Liabilities are ALWAYS displayed separately, NEVER subtracted (26:15)
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

TWOPLACES = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    """Round to 2 decimal places, half-up (bankers' rounding is *not* what
    finance staff expect on quarterly reports)."""
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def excess(inflow: Decimal, outflow: Decimal) -> Decimal:
    """The SACS blue-arrow amount that lands in Private Reserve each month."""
    return round_money(inflow - outflow)


def pr_target(monthly_expenses: Decimal, deductibles: Iterable[Decimal]) -> Decimal:
    """Personalized Private-Reserve target = 6x monthly expenses + all deductibles."""
    return round_money(monthly_expenses * 6 + sum(deductibles, Decimal("0")))


def retirement_totals(
    c1_retirement_balances: Iterable[Decimal],
    c2_retirement_balances: Iterable[Decimal],
) -> tuple[Decimal, Decimal]:
    """Return (client_1_retirement_total, client_2_retirement_total)."""
    c1 = round_money(sum(c1_retirement_balances, Decimal("0")))
    c2 = round_money(sum(c2_retirement_balances, Decimal("0")))
    return c1, c2


def non_retirement_total(balances: Iterable[Decimal]) -> Decimal:
    """Sum of every non-retirement account balance. Trust is EXCLUDED (24:28)."""
    return round_money(sum(balances, Decimal("0")))


def grand_total_net_worth(
    c1_retirement: Decimal,
    c2_retirement: Decimal,
    non_retirement: Decimal,
    trust_value: Decimal,
) -> Decimal:
    """Grand total = 4 boxes. Liabilities are NEVER subtracted (26:15)."""
    return round_money(c1_retirement + c2_retirement + non_retirement + trust_value)


def liabilities_total(liability_balances: Iterable[Decimal]) -> Decimal:
    """Sum of all liabilities. Displayed separately from net worth."""
    return round_money(sum(liability_balances, Decimal("0")))
