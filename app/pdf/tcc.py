"""TCC (Total Circle of Concern) PDF generator.

Single-page fixed-frame layout — reference target is ``assets/`` image
image-ff3fd559 (Sample Client — Green).

Layout summary:
  Top strip:      NAME / DATE (left) · GRAND TOTAL box (center) · empty (right)
  Top row:        C1 Ret Only box · C1 name oval · Liabilities total · C2 name oval · C2 Ret Only box
  Retirement row: 2 retirement bubbles per client (label, balance, a/o date, optional cash sub-bubble)
  Middle row:     RETIREMENT footer label · (spacer)
  Non-retirement: 2 columns of client non-retirement bubbles flanking a central Trust oval
  Bottom center:  Liabilities table + NON RETIREMENT TOTAL box
  Bottom right:   stale-data footnote (only when a balance is flagged stale)

Layout constants are in ``TCC_LAYOUT``; every position lives in a single
dict so tuning is O(1).
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from app.models import AccountSection, Report
from app.pdf.common import (
    draw_centered_text,
    draw_filled_circle,
    draw_rounded_box,
    money,
)
from app.pdf.theme import (
    BRAND_BLUE,
    CLIENT_OVAL_GREEN,
    CLIENT_OVAL_STROKE,
    FONT_BOLD,
    FONT_REGULAR,
    FOOTNOTE_SIZE,
    GRAY_100,
    GRAY_200,
    GRAY_400,
    GRAY_600,
    GRAY_800,
    OUTFLOW_RED,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    STALE_RED,
    TITLE_SIZE,
)
from app.reports.services import ReportEntryContext, build_entry_context, totals_from_report

CENTER_X = PAGE_WIDTH / 2

TCC_LAYOUT = {
    # Top strip (name/date/grand-total)
    "top_strip_y": PAGE_HEIGHT - 40,
    "grand_total_box": (CENTER_X - 65, PAGE_HEIGHT - 70, 130, 46),  # x, y, w, h
    # Client-name-oval row
    "name_oval_y": PAGE_HEIGHT - 130,
    "name_oval_w": 90,
    "name_oval_h": 40,
    "c1_col_x": 210,
    "c2_col_x": PAGE_WIDTH - 210,
    "ret_only_box_w": 130,
    "ret_only_box_h": 40,
    "liabilities_box_w": 150,
    "liabilities_box_h": 40,
    # Retirement bubble row
    "ret_row_y": PAGE_HEIGHT - 200,
    "ret_bubble_r": 44,
    "ret_bubble_gap": 20,
    # Non-retirement zone
    "trust_y": PAGE_HEIGHT - 380,
    "trust_r": 60,
    "non_ret_col_top_y": PAGE_HEIGHT - 320,
    "non_ret_bubble_r": 42,
    "non_ret_bubble_gap": 14,
    # Bottom liabilities table
    "liab_table_y": 200,
    "liab_table_h": 130,
    "liab_table_w": 220,
    # Non retirement total box (below liabilities)
    "non_ret_total_y": 50,
    "non_ret_total_w": 200,
    "non_ret_total_h": 32,
    # Stale footnote
    "stale_footnote_y": 68,
    # Border
    "outer_border": (28, 24, PAGE_WIDTH - 56, PAGE_HEIGHT - 48),
}


# ---------------------------------------------------------------------------- render


def render_tcc(report: Report, output_path: str | Path | BytesIO | None = None) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    canvas.setTitle(f"TCC · {report.client.display_name} · {report.meeting_date.isoformat()}")
    canvas.setAuthor("AW Client Portal")

    ctx = build_entry_context(report)
    totals = totals_from_report(report)

    _draw_outer_border(canvas)
    _draw_top_strip(canvas, report, totals)
    _draw_name_row(canvas, ctx, totals)
    _draw_retirement_row(canvas, ctx)
    _draw_retirement_section_label(canvas)
    _draw_non_retirement_zone(canvas, ctx, totals)
    _draw_liabilities_table(canvas, ctx)
    _draw_non_retirement_total(canvas, totals)
    _draw_stale_footnote(canvas, totals)
    _draw_footer(canvas, report)

    canvas.save()
    data = buffer.getvalue()

    if isinstance(output_path, (str, Path)):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
    return data


# ---------------------------------------------------------------------------- border


def _draw_outer_border(canvas: Canvas) -> None:
    x, y, w, h = TCC_LAYOUT["outer_border"]
    canvas.saveState()
    canvas.setStrokeColor(CLIENT_OVAL_STROKE)
    canvas.setLineWidth(0.8)
    canvas.rect(x, y, w, h, fill=0, stroke=1)
    canvas.restoreState()


# ---------------------------------------------------------------------------- top strip


def _draw_top_strip(canvas: Canvas, report: Report, totals) -> None:
    # NAME / DATE (upper-left)
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 9)
    canvas.drawString(50, PAGE_HEIGHT - 40, "NAME")
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawString(90, PAGE_HEIGHT - 40, report.client.display_name)
    canvas.setLineWidth(0.4)
    canvas.line(88, PAGE_HEIGHT - 42, 260, PAGE_HEIGHT - 42)

    canvas.setFont(FONT_REGULAR, 9)
    canvas.drawString(50, PAGE_HEIGHT - 55, "DATE")
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawString(90, PAGE_HEIGHT - 55, report.meeting_date.strftime("%B %d, %Y"))
    canvas.line(88, PAGE_HEIGHT - 57, 260, PAGE_HEIGHT - 57)

    # GRAND TOTAL box (center top)
    gx, gy, gw, gh = TCC_LAYOUT["grand_total_box"]
    draw_rounded_box(canvas, gx, gy, gw, gh, fill=GRAY_600, radius=4)
    draw_centered_text(
        canvas, gx + gw / 2, gy + gh - 14, "GRAND TOTAL", font=FONT_BOLD, size=10, color=(1, 1, 1)
    )
    draw_centered_text(
        canvas,
        gx + gw / 2,
        gy + 10,
        money(totals.grand_total),
        font=FONT_BOLD,
        size=TITLE_SIZE - 4,
        color=(1, 1, 1),
    )


# ---------------------------------------------------------------------------- name / subtotal row


def _draw_name_row(canvas: Canvas, ctx: ReportEntryContext, totals) -> None:
    layout = TCC_LAYOUT
    y = layout["name_oval_y"]

    # Client 1 Retirement Only (far left)
    c1_box_x = 50
    c1_box_y = y - layout["ret_only_box_h"] / 2
    draw_rounded_box(
        canvas,
        c1_box_x,
        c1_box_y,
        layout["ret_only_box_w"],
        layout["ret_only_box_h"],
        fill=GRAY_600,
        radius=4,
    )
    draw_centered_text(
        canvas,
        c1_box_x + layout["ret_only_box_w"] / 2,
        c1_box_y + layout["ret_only_box_h"] - 12,
        "Client 1 Retirement Only",
        font=FONT_BOLD,
        size=9,
        color=(1, 1, 1),
    )
    draw_centered_text(
        canvas,
        c1_box_x + layout["ret_only_box_w"] / 2,
        c1_box_y + 10,
        money(totals.c1_retirement),
        font=FONT_BOLD,
        size=12,
        color=(1, 1, 1),
    )

    # Client 1 name oval
    _draw_name_oval(
        canvas,
        layout["c1_col_x"],
        y,
        layout["name_oval_w"],
        layout["name_oval_h"],
        label=ctx.client.c1_first,
        subtitle=_member_meta(ctx.client, 1),
    )

    # Liabilities total (center)
    lx = CENTER_X - layout["liabilities_box_w"] / 2
    ly = y - layout["liabilities_box_h"] / 2
    draw_rounded_box(
        canvas,
        lx,
        ly,
        layout["liabilities_box_w"],
        layout["liabilities_box_h"],
        fill=GRAY_100,
        stroke=GRAY_400,
        radius=4,
    )
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 9)
    canvas.drawString(
        lx + 10,
        ly + layout["liabilities_box_h"] - 14,
        f"Liabilities:  {money(totals.liabilities_total)}",
    )
    latest_liab_date = _latest_date(lb.as_of_date for lb in ctx.report.liability_balances)
    if latest_liab_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 8)
        canvas.drawString(lx + 10, ly + 8, f"a/o {latest_liab_date.strftime('%m/%d/%Y')}")

    # Client 2 name oval + retirement box (only when married)
    if ctx.client.is_married:
        _draw_name_oval(
            canvas,
            layout["c2_col_x"],
            y,
            layout["name_oval_w"],
            layout["name_oval_h"],
            label=ctx.client.c2_first,
            subtitle=_member_meta(ctx.client, 2),
        )

        c2_box_x = PAGE_WIDTH - 50 - layout["ret_only_box_w"]
        c2_box_y = c1_box_y
        draw_rounded_box(
            canvas,
            c2_box_x,
            c2_box_y,
            layout["ret_only_box_w"],
            layout["ret_only_box_h"],
            fill=GRAY_600,
            radius=4,
        )
        draw_centered_text(
            canvas,
            c2_box_x + layout["ret_only_box_w"] / 2,
            c2_box_y + layout["ret_only_box_h"] - 12,
            "Client 2 Retirement Only",
            font=FONT_BOLD,
            size=9,
            color=(1, 1, 1),
        )
        draw_centered_text(
            canvas,
            c2_box_x + layout["ret_only_box_w"] / 2,
            c2_box_y + 10,
            money(totals.c2_retirement),
            font=FONT_BOLD,
            size=12,
            color=(1, 1, 1),
        )


def _draw_name_oval(
    canvas: Canvas, cx: float, cy: float, w: float, h: float, label: str, subtitle: str
) -> None:
    canvas.saveState()
    canvas.setFillColor(CLIENT_OVAL_GREEN)
    canvas.setStrokeColor(CLIENT_OVAL_STROKE)
    canvas.setLineWidth(1.2)
    canvas.roundRect(cx - w / 2, cy - h / 2, w, h, radius=h / 2, fill=1, stroke=1)
    canvas.restoreState()
    draw_centered_text(canvas, cx, cy + 5, label, font=FONT_BOLD, size=13, color=(1, 1, 1))
    canvas.setFillColor((1, 1, 1))
    canvas.setFont(FONT_REGULAR, 7)
    for i, line in enumerate(subtitle.split("\n")):
        canvas.drawCentredString(cx, cy - 6 - i * 8, line)


def _member_meta(client, side: int) -> str:
    if side == 1:
        return "Age\nDOB\nSSN"  # Compact placeholder — real data is in the client detail
    return "Age\nDOB\nSSN"


def _latest_date(dates):
    values = [d for d in dates if d is not None]
    return max(values) if values else None


# ---------------------------------------------------------------------------- retirement bubble row


def _draw_retirement_row(canvas: Canvas, ctx: ReportEntryContext) -> None:
    layout = TCC_LAYOUT
    y = layout["ret_row_y"]
    r = layout["ret_bubble_r"]
    gap = layout["ret_bubble_gap"]

    # 2 bubbles per side, centered under each client column.
    def _draw_side(rows, side_center_x):
        n = len(rows)
        if n == 0:
            return
        total_w = n * 2 * r + (n - 1) * gap
        start_x = side_center_x - total_w / 2 + r
        for i, row in enumerate(rows):
            bx = start_x + i * (2 * r + gap)
            _draw_retirement_bubble(canvas, bx, y, r, row)

    _draw_side(ctx.c1_retirement, layout["c1_col_x"])
    _draw_side(ctx.c2_retirement, layout["c2_col_x"])


def _draw_retirement_bubble(canvas: Canvas, cx: float, cy: float, r: float, row) -> None:
    draw_filled_circle(canvas, cx, cy, r, fill=(1, 1, 1), stroke=GRAY_400)

    label = row.account.display_name or row.account.kind.value.replace("_", " ").title()
    if len(label) > 15:
        label = label[:14] + "…"
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawCentredString(cx, cy + 22, "ACCT #")
    canvas.setFont(FONT_BOLD, 8)
    canvas.drawCentredString(cx, cy + 14, label)

    amount = money(row.balance.balance)
    if row.balance.is_stale:
        amount += " *"
    canvas.setFillColor(STALE_RED if row.balance.is_stale else GRAY_800)
    canvas.setFont(FONT_BOLD, 9)
    canvas.drawCentredString(cx, cy + 2, amount)

    if row.balance.as_of_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 7)
        canvas.drawCentredString(cx, cy - 10, f"a/o {row.balance.as_of_date.strftime('%m/%d/%y')}")

    # Cash sub-bubble (small, below main bubble) when set.
    if row.balance.cash_balance is not None and row.balance.cash_balance > Decimal("0"):
        sub_r = r * 0.45
        sub_cy = cy - r - sub_r + 4
        draw_filled_circle(canvas, cx, sub_cy, sub_r, fill=(1, 1, 1), stroke=GRAY_400)
        canvas.setFillColor(GRAY_800)
        canvas.setFont(FONT_BOLD, 7)
        canvas.drawCentredString(cx, sub_cy + 2, money(row.balance.cash_balance, with_cents=False))
        canvas.setFont(FONT_REGULAR, 6)
        canvas.drawCentredString(cx, sub_cy - 6, "Cash")


def _draw_retirement_section_label(canvas: Canvas) -> None:
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(45, PAGE_HEIGHT - 300, "RETIREMENT")
    canvas.drawRightString(PAGE_WIDTH - 45, PAGE_HEIGHT - 300, "RETIREMENT")

    canvas.setStrokeColor(GRAY_200)
    canvas.setLineWidth(0.5)
    canvas.line(45, PAGE_HEIGHT - 310, PAGE_WIDTH - 45, PAGE_HEIGHT - 310)


# ---------------------------------------------------------------------------- non-retirement zone


def _draw_non_retirement_zone(canvas: Canvas, ctx: ReportEntryContext, totals) -> None:
    layout = TCC_LAYOUT

    # Section labels
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(45, PAGE_HEIGHT - 325, "NON")
    canvas.drawString(45, PAGE_HEIGHT - 335, "RETIREMENT")
    canvas.drawRightString(PAGE_WIDTH - 45, PAGE_HEIGHT - 325, "NON")
    canvas.drawRightString(PAGE_WIDTH - 45, PAGE_HEIGHT - 335, "RETIREMENT")

    # Split non-retirement accounts left/right by owner (Client 1 vs Client 2 vs Joint).
    left_accounts = []
    right_accounts = []
    for row in ctx.non_retirement:
        if row.owner.value == "CLIENT2":
            right_accounts.append(row)
        else:
            left_accounts.append(row)

    _draw_bubble_column(
        canvas, layout["c1_col_x"] - 100, layout["non_ret_col_top_y"], left_accounts
    )
    _draw_bubble_column(
        canvas, layout["c2_col_x"] + 100, layout["non_ret_col_top_y"], right_accounts
    )

    # Trust in the center
    trust_row = ctx.trust[0] if ctx.trust else None
    tx = CENTER_X
    ty = layout["trust_y"]
    tr = layout["trust_r"]
    draw_filled_circle(canvas, tx, ty, tr, fill=(1, 1, 1), stroke=GRAY_400)
    trust_label = ctx.client.trust_label or "Family Trust"
    lines = _wrap(trust_label, 22)[:3]
    for i, line in enumerate(lines):
        draw_centered_text(
            canvas, tx, ty + 20 - i * 10, line, font=FONT_BOLD, size=8, color=GRAY_800
        )
    trust_balance = trust_row.balance.balance if trust_row else Decimal("0")
    draw_centered_text(
        canvas, tx, ty - 4, money(trust_balance), font=FONT_BOLD, size=10, color=GRAY_800
    )
    if trust_row and trust_row.balance.as_of_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 7)
        canvas.drawCentredString(
            tx, ty - 16, f"a/o {trust_row.balance.as_of_date.strftime('%m/%d/%y')}"
        )


def _draw_bubble_column(canvas: Canvas, cx: float, top_y: float, rows) -> None:
    layout = TCC_LAYOUT
    r = layout["non_ret_bubble_r"]
    gap = layout["non_ret_bubble_gap"]
    for i, row in enumerate(rows):
        cy = top_y - (2 * r + gap) * i - r
        _draw_non_retirement_bubble(canvas, cx, cy, r, row)


def _draw_non_retirement_bubble(canvas: Canvas, cx: float, cy: float, r: float, row) -> None:
    draw_filled_circle(canvas, cx, cy, r, fill=(1, 1, 1), stroke=GRAY_400)
    label = row.account.display_name or row.account.kind.value.replace("_", " ").title()
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawCentredString(cx, cy + 18, "ACCT #")
    canvas.setFont(FONT_BOLD, 7)
    # Truncate long labels
    if len(label) > 18:
        label = label[:17] + "…"
    canvas.drawCentredString(cx, cy + 10, label)

    amount = money(row.balance.balance)
    if row.balance.is_stale:
        amount += " *"
    canvas.setFillColor(STALE_RED if row.balance.is_stale else GRAY_800)
    canvas.setFont(FONT_BOLD, 8)
    canvas.drawCentredString(cx, cy - 2, amount)

    if row.balance.as_of_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 7)
        canvas.drawCentredString(cx, cy - 14, f"a/o {row.balance.as_of_date.strftime('%m/%d/%y')}")


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------------------------------------------------------------------------- liabilities table


def _draw_liabilities_table(canvas: Canvas, ctx: ReportEntryContext) -> None:
    if not ctx.liabilities:
        return
    layout = TCC_LAYOUT
    x = CENTER_X - layout["liab_table_w"] / 2
    y = layout["liab_table_y"]
    w = layout["liab_table_w"]

    # Header row: "Liabilities:"
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 9)
    canvas.drawCentredString(x + w / 2, y + 100, "Liabilities:")

    # Table box
    row_h = 12
    total_h = len(ctx.liabilities) * row_h + 10
    canvas.saveState()
    canvas.setStrokeColor(GRAY_400)
    canvas.setLineWidth(0.5)
    canvas.rect(x, y + 90 - total_h, w, total_h, fill=0, stroke=1)
    canvas.restoreState()

    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 8)
    for i, row in enumerate(ctx.liabilities):
        row_y = y + 80 - i * row_h
        canvas.drawString(x + 8, row_y, row.liability.label)
        canvas.drawRightString(x + w - 8, row_y, money(row.balance.balance))


def _draw_non_retirement_total(canvas: Canvas, totals) -> None:
    layout = TCC_LAYOUT
    x = CENTER_X - layout["non_ret_total_w"] / 2
    y = layout["non_ret_total_y"]
    w = layout["non_ret_total_w"]
    h = layout["non_ret_total_h"]

    draw_rounded_box(canvas, x, y, w, h, fill=GRAY_600, radius=4)
    draw_centered_text(
        canvas,
        x + w / 2,
        y + h - 12,
        "NON RETIREMENT TOTAL",
        font=FONT_BOLD,
        size=9,
        color=(1, 1, 1),
    )
    draw_centered_text(
        canvas,
        x + w / 2,
        y + 6,
        money(totals.non_retirement),
        font=FONT_BOLD,
        size=13,
        color=(1, 1, 1),
    )


# ---------------------------------------------------------------------------- footnote + footer


def _draw_stale_footnote(canvas: Canvas, totals) -> None:
    if not totals.stale_present:
        return
    canvas.setFillColor(STALE_RED)
    canvas.setFont(FONT_REGULAR, FOOTNOTE_SIZE)
    canvas.drawRightString(
        PAGE_WIDTH - 45,
        TCC_LAYOUT["stale_footnote_y"],
        "* Indicates we do not have up to date information",
    )


def _draw_footer(canvas: Canvas, report: Report) -> None:
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawString(45, 20, f"AW Client Portal · {report.client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 45, 20, "TCC · Page 1 of 1")


# Backwards-compat: keep the old symbol name so external imports don't break.
_ = OUTFLOW_RED, BRAND_BLUE, AccountSection  # keep imports referenced
