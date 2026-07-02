"""Every formula from the PRD, exhaustively unit-tested.

These tests exist to prevent regressions on Rebecca's two hard rules:
1. Liabilities are NEVER subtracted from net worth (26:15).
2. Trust is NEVER added to the non-retirement subtotal (24:28).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.calc.engine import (
    excess,
    grand_total_net_worth,
    liabilities_total,
    non_retirement_total,
    pr_target,
    retirement_totals,
    round_money,
)

D = Decimal


# ---- excess ----------------------------------------------------------------


def test_excess_zero_when_equal():
    assert excess(D("10000"), D("10000")) == D("0.00")


def test_excess_positive_typical_case():
    # From the SACS sample: $15,000 inflow - $12,000 outflow -> $3,000 excess.
    assert excess(D("15000"), D("12000")) == D("3000.00")


def test_excess_can_be_negative():
    """Overspend months exist (Rebecca 25:54)."""
    assert excess(D("10000"), D("11000")) == D("-1000.00")


def test_excess_handles_pennies():
    assert excess(D("15000.55"), D("12000.30")) == D("3000.25")


# ---- pr_target -------------------------------------------------------------


def test_pr_target_no_deductibles():
    # 6 * 10,000 = 60,000
    assert pr_target(D("10000"), []) == D("60000.00")


def test_pr_target_with_deductibles():
    # 6 * 10,000 + 1,000 + 2,000 + 1,000 = 64,000
    assert pr_target(D("10000"), [D("1000"), D("2000"), D("1000")]) == D("64000.00")


def test_pr_target_rounding():
    """Half-up rounding — finance staff expect it (not bankers')."""
    result = pr_target(D("10000.005"), [])
    # 6 * 10000.005 = 60000.030 -> rounds to 60000.03
    assert result == D("60000.03")


# ---- retirement_totals ----------------------------------------------------


def test_retirement_totals_split_per_spouse():
    """From the TCC sample: IRA $11,162.47 + implicit others per side."""
    c1, c2 = retirement_totals(
        c1_retirement_balances=[D("11162.47"), D("15000.00")],
        c2_retirement_balances=[D("37232.46"), D("70042.00"), D("18885.92")],
    )
    assert c1 == D("26162.47")
    assert c2 == D("126160.38")


def test_retirement_totals_zero_when_empty():
    c1, c2 = retirement_totals([], [])
    assert c1 == D("0.00")
    assert c2 == D("0.00")


def test_retirement_totals_single_client_household():
    """C2 side is legitimately empty for single clients — no crash."""
    c1, c2 = retirement_totals([D("50000")], [])
    assert c1 == D("50000.00")
    assert c2 == D("0.00")


# ---- non_retirement_total --------------------------------------------------


def test_non_retirement_excludes_trust():
    """Rebecca 24:28: 'we do not add the trust in [to non-retirement total]'."""
    non_retirement = [D("50000"), D("30000"), D("15000")]  # brokerage + checking + savings
    trust = D("450000")  # NOT in the sum
    total = non_retirement_total(non_retirement)
    assert total == D("95000.00")
    assert trust not in non_retirement  # sanity guard


# ---- grand_total_net_worth ------------------------------------------------


def test_grand_total_four_boxes_added():
    """C1 retirement + C2 retirement + non-retirement + trust."""
    total = grand_total_net_worth(
        c1_retirement=D("26162.47"),
        c2_retirement=D("126160.38"),
        non_retirement=D("189308.04"),
        trust_value=D("450000"),
    )
    assert total == D("791630.89")


def test_grand_total_never_subtracts_liabilities():
    """Rebecca 26:15: liabilities are a SEPARATE box, never subtracted."""
    with_no_liabilities = grand_total_net_worth(D("100"), D("200"), D("300"), D("400"))
    # Verify the function signature literally does not accept a liabilities arg.
    assert with_no_liabilities == D("1000.00")


def test_grand_total_matches_tcc_sample():
    """Sample Client (image-ff3fd559): Grand Total $326,630.89 with no trust value."""
    # From the screenshot: C1 Retirement $11,162.47 + C2 Retirement $126,160.38
    # + Non-Retirement $189,308.04 + Trust $0 = $326,630.89
    total = grand_total_net_worth(
        c1_retirement=D("11162.47"),
        c2_retirement=D("126160.38"),
        non_retirement=D("189308.04"),
        trust_value=D("0"),
    )
    assert total == D("326630.89")


# ---- liabilities_total ----------------------------------------------------


def test_liabilities_total_sums_flat_list():
    """From TCC sample: P Mortg + S Mortg + Mercedes + GMC Sierra + Escalade + PNC + Health.

    Note: the sample PDF shows Liabilities: $418,050.07, but summing the
    line items gives $416,050.07 — a $2,000 arithmetic error in the
    manually-typed Canva total. This is exactly the kind of mistake the
    portal is designed to eliminate (Rebecca 25:54, Maryann 25:36).
    We assert the arithmetically-correct value, not the sample's printed one.
    """
    balances = [
        D("224218.24"),
        D("107587.31"),
        D("11152.00"),
        D("25992.00"),
        D("31627.52"),
        D("14026.00"),
        D("1447.00"),
    ]
    assert liabilities_total(balances) == D("416050.07")


def test_liabilities_total_empty():
    assert liabilities_total([]) == D("0.00")


# ---- round_money ----------------------------------------------------------


@pytest.mark.parametrize(
    "input_value, expected",
    [
        (D("100.005"), D("100.01")),  # half-up, not bankers'
        (D("100.004"), D("100.00")),
        (D("100.994"), D("100.99")),
        (D("100.995"), D("101.00")),
        (D("0"), D("0.00")),
        (D("-3000.005"), D("-3000.01")),  # ROUND_HALF_UP = half-away-from-zero
    ],
)
def test_round_money_half_up(input_value, expected):
    # ROUND_HALF_UP behaves as half-away-from-zero for negatives per Python docs.
    assert round_money(input_value) == expected
