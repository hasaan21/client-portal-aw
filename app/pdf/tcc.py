"""TCC (Total Circle of Concern) PDF generator.

Single-page fixed-frame layout — reference target is ``assets/`` image
image-ff3fd559 (Sample Client — Green).

Structure:
  Top             Title bar
  Upper-left      Client-1 retirement column (label, custodian, last4, amount)
  Upper-right     Client-2 retirement column
  Center-top      Trust label + address + trust value bubble
  Center-mid      Non-retirement bubble
  Center-bottom   GRAND TOTAL bubble (largest visual anchor)
  Bottom          Liabilities table
  Very bottom     Client-household name oval (green)

Stale balances get a red '*' after the amount and a corresponding
footnote near the client oval.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from app.models import Report
from app.pdf.common import (
    draw_centered_text,
    draw_filled_circle,
    draw_pill,
    draw_rounded_box,
    money,
)
from app.pdf.theme import (
    BRAND_BLUE,
    BRAND_BLUE_DARK,
    BRAND_BLUE_LIGHT,
    CLIENT_OVAL_GREEN,
    CLIENT_OVAL_STROKE,
    FONT_BOLD,
    FONT_REGULAR,
    FOOTNOTE_SIZE,
    GRAY_100,
    GRAY_400,
    GRAY_600,
    GRAY_800,
    OUTFLOW_RED,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    STALE_RED,
    SUBTITLE_SIZE,
    TITLE_SIZE,
)
from app.reports.services import ReportEntryContext, build_entry_context, totals_from_report

CENTER_X = PAGE_WIDTH / 2

TCC_LAYOUT = {
    "title_y": PAGE_HEIGHT - 55,
    "subtitle_y": PAGE_HEIGHT - 75,
    "column_top_y": PAGE_HEIGHT - 130,
    # Column x-centers
    "c1_col_x": 120,
    "c2_col_x": PAGE_WIDTH - 120,
    "center_x": CENTER_X,
    # Bubble sizing
    "bubble_width": 180,
    "bubble_height": 58,
    "bubble_gap": 12,
    # Trust
    "trust_y": PAGE_HEIGHT - 190,
    "trust_bubble_r": 60,
    # Grand total
    "grand_total_y": 320,
    "grand_total_r": 78,
    # Non-retirement
    "non_ret_y": 460,
    # Liabilities region
    "liabilities_top_y": 220,
    "liabilities_row_h": 16,
    # Client oval
    "client_oval_y": 60,
    "client_oval_w": 340,
    "client_oval_h": 46,
}


# ---------------------------------------------------------------------------- render


def render_tcc(report: Report, output_path: str | Path | BytesIO | None = None) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    canvas.setTitle(f"TCC · {report.client.display_name} · {report.meeting_date.isoformat()}")
    canvas.setAuthor("AW Client Portal")

    ctx = build_entry_context(report)
    totals = totals_from_report(report)

    _draw_header(canvas, report)
    _draw_retirement_columns(canvas, ctx)
    _draw_center_stack(canvas, ctx, totals)
    _draw_liabilities(canvas, ctx)
    _draw_client_oval(canvas, ctx)
    _draw_stale_footnote(canvas, totals, ctx)
    _draw_footer(canvas, report)

    canvas.save()
    data = buffer.getvalue()

    if isinstance(output_path, (str, Path)):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
    return data


# ---------------------------------------------------------------------------- header


def _draw_header(canvas: Canvas, report: Report) -> None:
    draw_centered_text(
        canvas,
        CENTER_X,
        TCC_LAYOUT["title_y"],
        "Total Circle of Concern (TCC)",
        font=FONT_BOLD,
        size=TITLE_SIZE,
        color=GRAY_800,
    )
    draw_centered_text(
        canvas,
        CENTER_X,
        TCC_LAYOUT["subtitle_y"],
        f"{report.client.display_name} — {report.meeting_date.strftime('%B %d, %Y')}",
        font=FONT_REGULAR,
        size=SUBTITLE_SIZE,
        color=GRAY_600,
    )


# ---------------------------------------------------------------------------- retirement columns


def _draw_retirement_columns(canvas: Canvas, ctx: ReportEntryContext) -> None:
    layout = TCC_LAYOUT
    client = ctx.client

    # Left column heading + bubbles
    _draw_column_heading(
        canvas, layout["c1_col_x"], layout["column_top_y"] + 20, f"{client.c1_first}'s Retirement"
    )
    _draw_bubble_stack(canvas, layout["c1_col_x"], layout["column_top_y"] - 6, ctx.c1_retirement)

    # Right column
    right_heading = f"{client.c2_first}'s Retirement" if client.is_married else "Additional"
    _draw_column_heading(canvas, layout["c2_col_x"], layout["column_top_y"] + 20, right_heading)
    _draw_bubble_stack(canvas, layout["c2_col_x"], layout["column_top_y"] - 6, ctx.c2_retirement)


def _draw_column_heading(canvas: Canvas, cx: float, cy: float, text: str) -> None:
    canvas.setFillColor(BRAND_BLUE)
    canvas.setFont(FONT_BOLD, 11)
    canvas.drawCentredString(cx, cy, text)


def _draw_bubble_stack(canvas: Canvas, cx: float, top_y: float, rows: list) -> None:
    """Stack ``rows`` (list of BalanceRow) as bubbles starting at cy=top_y
    and moving downward."""
    bh = TCC_LAYOUT["bubble_height"]
    gap = TCC_LAYOUT["bubble_gap"]

    if not rows:
        canvas.setFillColor(GRAY_400)
        canvas.setFont(FONT_REGULAR, 9)
        canvas.drawCentredString(cx, top_y - 20, "(none)")
        return

    for i, row in enumerate(rows):
        cy = top_y - (bh + gap) * i - bh / 2
        _draw_account_bubble(canvas, cx, cy, row)


def _draw_account_bubble(canvas: Canvas, cx: float, cy: float, row) -> None:
    bw = TCC_LAYOUT["bubble_width"]
    bh = TCC_LAYOUT["bubble_height"]

    # Body: soft blue fill, subtle border
    draw_rounded_box(
        canvas,
        cx - bw / 2,
        cy - bh / 2,
        bw,
        bh,
        fill=BRAND_BLUE_LIGHT,
        stroke=BRAND_BLUE,
        radius=10,
    )

    label = row.account.display_name or row.account.kind.value.replace("_", " ").title()
    custodian = row.account.custodian or ""
    last4 = f"#{row.account.last4}" if row.account.last4 else ""
    meta = " · ".join(x for x in [custodian, last4] if x)

    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawCentredString(cx, cy + 14, label)

    if meta:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 8)
        canvas.drawCentredString(cx, cy + 3, meta)

    amount_str = money(row.balance.balance)
    if row.balance.is_stale:
        amount_str += " *"
    canvas.setFillColor(STALE_RED if row.balance.is_stale else GRAY_800)
    canvas.setFont(FONT_BOLD, 12)
    canvas.drawCentredString(cx, cy - 12, amount_str)

    # Cash sub-amount (small, right-aligned) for investment/retirement kinds.
    if row.balance.cash_balance is not None and row.balance.cash_balance > Decimal("0"):
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 7)
        canvas.drawCentredString(
            cx,
            cy - 22,
            f"+ {money(row.balance.cash_balance)} cash",
        )


# ---------------------------------------------------------------------------- center stack (trust, non-ret, grand total)


def _draw_center_stack(canvas: Canvas, ctx: ReportEntryContext, totals) -> None:
    layout = TCC_LAYOUT
    client = ctx.client
    cx = layout["center_x"]

    # Trust bubble at top
    ty = layout["trust_y"]
    tr = layout["trust_bubble_r"]
    draw_filled_circle(canvas, cx, ty, tr, fill=BRAND_BLUE_DARK)

    trust_lines = client.trust_label.split()
    if len(trust_lines) <= 2:
        draw_centered_text(
            canvas, cx, ty + 6, client.trust_label, font=FONT_BOLD, size=11, color=(1, 1, 1)
        )
    else:
        draw_centered_text(
            canvas, cx, ty + 12, trust_lines[0], font=FONT_BOLD, size=10, color=(1, 1, 1)
        )
        draw_centered_text(
            canvas, cx, ty - 1, " ".join(trust_lines[1:]), font=FONT_BOLD, size=10, color=(1, 1, 1)
        )

    draw_pill(canvas, cx, ty - 22, 100, 20, fill=(1, 1, 1), stroke=(0.7, 0.75, 0.8))
    draw_centered_text(
        canvas, cx, ty - 27, money(totals.trust_value), font=FONT_BOLD, size=11, color=GRAY_800
    )

    # Trust property address below the bubble (small, muted)
    if client.trust_property_address:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 8)
        for j, chunk in enumerate(_wrap(client.trust_property_address, 40)[:2]):
            canvas.drawCentredString(cx, ty - tr - 12 - j * 10, chunk)

    # Non-retirement bubble
    nry = layout["non_ret_y"]
    draw_rounded_box(
        canvas, cx - 100, nry - 25, 200, 50, fill=GRAY_100, stroke=BRAND_BLUE, radius=10
    )
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawCentredString(cx, nry + 8, "Non-Retirement")
    canvas.setFont(FONT_BOLD, 13)
    canvas.drawCentredString(cx, nry - 10, money(totals.non_retirement))

    # Grand Total (large brand-colored circle, most prominent element)
    gty = layout["grand_total_y"]
    gtr = layout["grand_total_r"]
    draw_filled_circle(canvas, cx, gty, gtr, fill=BRAND_BLUE)
    draw_centered_text(
        canvas, cx, gty + 20, "GRAND TOTAL", font=FONT_BOLD, size=11, color=(1, 1, 1)
    )
    draw_pill(canvas, cx, gty - 8, 140, 26, fill=(1, 1, 1), stroke=(0.7, 0.75, 0.8))
    draw_centered_text(
        canvas, cx, gty - 14, money(totals.grand_total), font=FONT_BOLD, size=14, color=GRAY_800
    )


def _wrap(text: str, width: int) -> list[str]:
    """Naive whitespace wrap — enough for one-line trust addresses."""
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


# ---------------------------------------------------------------------------- liabilities


def _draw_liabilities(canvas: Canvas, ctx: ReportEntryContext) -> None:
    layout = TCC_LAYOUT
    if not ctx.liabilities:
        return

    top_y = layout["liabilities_top_y"]
    box_x = 60
    box_w = PAGE_WIDTH - 120
    row_h = layout["liabilities_row_h"]
    body_h = row_h * (len(ctx.liabilities) + 2)  # +header +total

    draw_rounded_box(
        canvas,
        box_x,
        top_y - body_h + 6,
        box_w,
        body_h,
        fill=GRAY_100,
        stroke=OUTFLOW_RED,
        radius=6,
    )

    # Section title
    canvas.setFillColor(OUTFLOW_RED)
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawCentredString(CENTER_X, top_y - 4, "LIABILITIES")

    # Rows
    total = Decimal("0.00")
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 9)
    label_x = box_x + 12
    rate_x = box_x + box_w / 2
    amount_x = box_x + box_w - 12

    for i, row in enumerate(ctx.liabilities):
        y = top_y - 20 - row_h * i
        liab = row.liability
        lb = row.balance
        canvas.drawString(label_x, y, liab.label)
        if liab.interest_rate is not None:
            canvas.setFillColor(GRAY_600)
            canvas.drawCentredString(rate_x, y, f"{liab.interest_rate:.3f}%")
            canvas.setFillColor(GRAY_800)
        canvas.drawRightString(amount_x, y, money(lb.balance))
        total += lb.balance

    # Total row
    y_total = top_y - 20 - row_h * len(ctx.liabilities) - 4
    canvas.setStrokeColor(GRAY_400)
    canvas.setLineWidth(0.5)
    canvas.line(label_x, y_total + 8, amount_x, y_total + 8)
    canvas.setFillColor(OUTFLOW_RED)
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawString(label_x, y_total - 2, "Total liabilities")
    canvas.drawRightString(amount_x, y_total - 2, money(total))


# ---------------------------------------------------------------------------- client name oval


def _draw_client_oval(canvas: Canvas, ctx: ReportEntryContext) -> None:
    layout = TCC_LAYOUT
    cy = layout["client_oval_y"]
    w = layout["client_oval_w"]
    h = layout["client_oval_h"]

    canvas.saveState()
    canvas.setFillColor(CLIENT_OVAL_GREEN)
    canvas.setStrokeColor(CLIENT_OVAL_STROKE)
    canvas.setLineWidth(1.2)
    canvas.roundRect(CENTER_X - w / 2, cy - h / 2, w, h, radius=h / 2, fill=1, stroke=1)
    canvas.restoreState()

    label = ctx.client.display_name
    if ctx.client.is_married:
        label = f"{ctx.client.c1_first} & {ctx.client.c2_first} {ctx.client.c2_last}"
    draw_centered_text(canvas, CENTER_X, cy - 5, label, font=FONT_BOLD, size=16, color=(1, 1, 1))


# ---------------------------------------------------------------------------- footnote + footer


def _draw_stale_footnote(canvas: Canvas, totals, ctx: ReportEntryContext) -> None:
    if not totals.stale_present:
        return
    canvas.setFillColor(STALE_RED)
    canvas.setFont(FONT_REGULAR, FOOTNOTE_SIZE)
    canvas.drawCentredString(
        CENTER_X,
        TCC_LAYOUT["client_oval_y"] + 30,
        "* Balance not up to date — will be refreshed at next quarterly review.",
    )


def _draw_footer(canvas: Canvas, report: Report) -> None:
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(36, 24, f"AW Client Portal · {report.client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 36, 24, "TCC · Page 1 of 1")
