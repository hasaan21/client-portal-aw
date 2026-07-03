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
    CLIENT_ACCENT_LIGHT,
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
    TITLE_SIZE,
)
from app.reports.services import ReportEntryContext, build_entry_context, totals_from_report

CENTER_X = PAGE_WIDTH / 2

TCC_LAYOUT = {
    # Top strip (name/date/grand-total) -----------------------------------
    "top_strip_y": PAGE_HEIGHT - 40,
    # Grand Total moved down ~15pt so it sits between the NAME/DATE band
    # and the client-oval row (matching the reference sample).
    "grand_total_box": (CENTER_X - 65, PAGE_HEIGHT - 85, 130, 46),  # x, y, w, h
    # Client-name-oval row ------------------------------------------------
    # Widths tuned so 5 elements (2 pills + 2 ovals + center liabilities
    # pill) fit with visible gaps rather than overlapping. The Liabilities
    # pill is wider (125) so "Liabilities:  $XXX,XXX.XX" fits without
    # overflowing at 9pt font.
    "name_oval_y": PAGE_HEIGHT - 138,
    "name_oval_w": 72,
    "name_oval_h": 60,
    "c1_col_x": 205,
    "c2_col_x": PAGE_WIDTH - 205,
    "ret_only_box_w": 115,
    "ret_only_box_h": 40,
    "liabilities_box_w": 120,
    "liabilities_box_h": 40,
    # 4-column grid for bubbles (retirement + non-retirement) -------------
    # Inner columns aligned with the client-oval X (205 / PAGE-205) so
    # each spouse's retirement bubbles sit visually under their oval.
    # Outer columns pulled inward to 128 so bubbles don't clip edge labels.
    "grid_cols_x": (128, 205, PAGE_WIDTH - 205, PAGE_WIDTH - 128),
    # Retirement bubbles --------------------------------------------------
    # Radius nudged up (32 → 35) so the circles read as substantial;
    # column X positions widen just enough to keep a ~7pt gap between
    # outer and inner bubbles.
    "ret_row_top_y": PAGE_HEIGHT - 245,
    "ret_bubble_r": 35,
    "ret_row_stack_delta": 80,
    "ret_zone_bottom_y": PAGE_HEIGHT - 372,
    "ret_zone_divider_y": PAGE_HEIGHT - 382,
    # Non-retirement zone -------------------------------------------------
    "non_ret_zone_top_y": PAGE_HEIGHT - 395,
    "non_ret_row_top_y": PAGE_HEIGHT - 448,
    "non_ret_bubble_r": 34,
    "non_ret_row_stack_delta": 76,
    # Trust in the vertical / horizontal center of the non-retirement zone
    "trust_x": CENTER_X,
    "trust_y": PAGE_HEIGHT - 470,
    "trust_r": 50,
    # Bottom liabilities table -------------------------------------------
    "liab_table_y": 110,  # Height incl. inline "Liabilities:" header ~108pt.
    "liab_table_w": 250,
    # Non retirement total box (below liabilities) ------------------------
    "non_ret_total_y": 65,
    "non_ret_total_w": 220,
    "non_ret_total_h": 34,
    # Stale footnote ------------------------------------------------------
    "stale_footnote_y": 40,
    # Border --------------------------------------------------------------
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

    if isinstance(output_path, str | Path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
    return data


# ---------------------------------------------------------------------------- border


def _draw_outer_border(canvas: Canvas) -> None:
    """Light olive-green content-area border + a dotted olive vertical
    divider between Client 1 and Client 2 sides.

    Both the border and the divider use ``CLIENT_ACCENT_LIGHT`` — a
    muted khaki tint chosen so these chrome elements recede rather than
    compete with the ovals and text.
    """
    x, y, w, h = TCC_LAYOUT["outer_border"]
    canvas.saveState()
    canvas.setStrokeColor(CLIENT_ACCENT_LIGHT)
    canvas.setLineWidth(1.2)
    canvas.rect(x, y, w, h, fill=0, stroke=1)

    # Solid vertical divider between the two client sides. It runs from
    # just under the outer border down through the non-retirement zone;
    # the centered Grand-Total box and Liabilities pill (drawn AFTER
    # this line) cover their own bands so the divider only shows in the
    # gaps between them.
    canvas.setStrokeColor(CLIENT_ACCENT_LIGHT)
    canvas.setLineWidth(0.8)
    divider_top = y + h - 6  # just inside the top border
    divider_bottom = TCC_LAYOUT["non_ret_row_top_y"] - TCC_LAYOUT["non_ret_row_stack_delta"] - 20
    canvas.line(CENTER_X, divider_top, CENTER_X, divider_bottom)
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
    c1_box_x = 45
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
        size=8,
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

        c2_box_x = PAGE_WIDTH - 45 - layout["ret_only_box_w"]
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
            size=8,
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
    # Name in the upper half; meta lines fit inside the lower half. Line
    # spacing (6.5pt @ 6.5pt font) is tuned so a 3-line block sits inside a
    # 52pt-tall oval without touching the border.
    lines = [line for line in subtitle.split("\n") if line]
    draw_centered_text(canvas, cx, cy + 11, label, font=FONT_BOLD, size=13, color=(1, 1, 1))
    canvas.setFillColor((1, 1, 1))
    canvas.setFont(FONT_REGULAR, 6.5)
    for i, line in enumerate(lines):
        canvas.drawCentredString(cx, cy - 1 - i * 7, line)


def _member_meta(client, side: int) -> str:
    """Compact per-spouse header shown inside the name oval.

    Renders age / DOB / SSN when populated on the client; falls back to a
    bare label so the oval never shows an orphan word. Kept to three short
    lines so it fits inside a 90x40 pill.
    """
    if side == 1:
        age, dob, last4 = client.c1_age, client.c1_dob, client.c1_ssn_last4
    else:
        age, dob, last4 = client.c2_age, client.c2_dob, client.c2_ssn_last4
    lines: list[str] = []
    if age is not None:
        lines.append(f"Age {age}")
    if dob is not None:
        lines.append(f"DOB {dob.strftime('%m/%d/%y')}")
    if last4:
        lines.append(f"SSN ****{last4}")
    return "\n".join(lines)


def _latest_date(dates):
    values = [d for d in dates if d is not None]
    return max(values) if values else None


# ---------------------------------------------------------------------------- retirement bubble row


def _draw_retirement_row(canvas: Canvas, ctx: ReportEntryContext) -> None:
    """4-column grid: Client 1 fills the two left columns (outer, inner),
    Client 2 fills the two right columns (inner, outer). N accounts are
    split (N//2, N-N//2) with the extra bubble stacked in the inner
    column — matches the reference sample where a 3-account spouse has
    two stacked accounts inner and one outer."""
    layout = TCC_LAYOUT
    top_y = layout["ret_row_top_y"]
    r = layout["ret_bubble_r"]
    stack_delta = layout["ret_row_stack_delta"]
    outer_l, inner_l, inner_r, outer_r = layout["grid_cols_x"]

    def _split(accounts):
        # First half to outer column, remainder to inner column so extras
        # stack in the inner (matching the reference).
        n = len(accounts)
        half = n // 2
        return accounts[:half], accounts[half:]

    def _draw_column(col_x, rows):
        for i, row in enumerate(rows):
            cy = top_y - i * stack_delta
            _draw_retirement_bubble(canvas, col_x, cy, r, row)

    c1_outer, c1_inner = _split(ctx.c1_retirement)
    c2_outer, c2_inner = _split(ctx.c2_retirement)
    _draw_column(outer_l, c1_outer)
    _draw_column(inner_l, c1_inner)
    _draw_column(inner_r, c2_inner)
    _draw_column(outer_r, c2_outer)


def _draw_retirement_bubble(canvas: Canvas, cx: float, cy: float, r: float, row) -> None:
    """Retirement account bubble.

    When a cash balance is present, a smaller Cash sub-bubble is drawn
    INSIDE the lower portion of the main bubble (not below it) — this
    matches the reference sample. The main-bubble text is compressed
    into the upper portion to make room.
    """
    draw_filled_circle(canvas, cx, cy, r, fill=(1, 1, 1), stroke=GRAY_400)

    has_cash = row.balance.cash_balance is not None and row.balance.cash_balance > Decimal("0")

    # Label — wrap onto up to 2 lines instead of "…"-truncating so the
    # full account name always renders (e.g. "ROTH IRA", "Vanguard IRA").
    raw_label = row.account.display_name or row.account.kind.value.replace("_", " ").title()
    label_lines = _wrap(raw_label, 12)[:2]

    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 6.5)
    canvas.drawCentredString(cx, cy + r - 8, "ACCT #")
    canvas.setFont(FONT_BOLD, 8)
    for i, line in enumerate(label_lines):
        canvas.drawCentredString(cx, cy + r - 18 - i * 9, line)

    # Vertical anchor for balance/as-of shifts UP when cash sub-bubble
    # will be drawn in the bottom half.
    amount_y = cy - 2 if has_cash else cy - 6
    aof_y = cy - 12 if has_cash else cy - 16

    amount = money(row.balance.balance)
    if row.balance.is_stale:
        amount += " *"
    canvas.setFillColor(STALE_RED if row.balance.is_stale else GRAY_800)
    canvas.setFont(FONT_BOLD, 8.5)
    canvas.drawCentredString(cx, amount_y, amount)

    if row.balance.as_of_date and not has_cash:
        # Hide the a/o date when the cash sub-bubble is present — the
        # bubble is too small to hold both, and the parent a/o is
        # already implied by the meeting date.
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 6.5)
        canvas.drawCentredString(cx, aof_y, f"a/o {row.balance.as_of_date.strftime('%m/%d/%y')}")

    # Cash sub-bubble drawn INSIDE the lower portion of the main bubble.
    if has_cash:
        sub_r = r * 0.36
        sub_cy = cy - r + sub_r + 2  # bottom edge sits 2pt above main bottom
        draw_filled_circle(canvas, cx, sub_cy, sub_r, fill=(1, 1, 1), stroke=GRAY_400)
        canvas.setFillColor(GRAY_800)
        canvas.setFont(FONT_BOLD, 7)
        canvas.drawCentredString(cx, sub_cy + 1, money(row.balance.cash_balance, with_cents=False))
        canvas.setFont(FONT_REGULAR, 6)
        canvas.drawCentredString(cx, sub_cy - 6, "Cash")


def _draw_retirement_section_label(canvas: Canvas) -> None:
    """Edge-anchored `RETIREMENT` labels at the bottom of the zone
    (both sides) + a thin divider separating retirement from
    non-retirement. Labels use the light olive accent so they match
    the outer border / vertical divider."""
    y = TCC_LAYOUT["ret_zone_bottom_y"]
    canvas.setFillColor(CLIENT_ACCENT_LIGHT)
    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.drawString(45, y, "RETIREMENT")
    canvas.drawRightString(PAGE_WIDTH - 45, y, "RETIREMENT")
    # Horizontal separator uses the same light olive accent as the outer
    # border / vertical divider so all chrome lines match.
    canvas.setStrokeColor(CLIENT_ACCENT_LIGHT)
    canvas.setLineWidth(0.6)
    canvas.line(
        45,
        TCC_LAYOUT["ret_zone_divider_y"],
        PAGE_WIDTH - 45,
        TCC_LAYOUT["ret_zone_divider_y"],
    )


# ---------------------------------------------------------------------------- non-retirement zone


def _draw_non_retirement_zone(canvas: Canvas, ctx: ReportEntryContext, totals) -> None:
    """4-column grid mirroring the retirement zone above, with the trust
    circle centered between the inner columns. Joint accounts count as
    Client 1's for grouping purposes (they show on the left)."""
    layout = TCC_LAYOUT
    outer_l, inner_l, inner_r, outer_r = layout["grid_cols_x"]
    top_y = layout["non_ret_row_top_y"]
    r = layout["non_ret_bubble_r"]
    stack_delta = layout["non_ret_row_stack_delta"]

    # Group accounts by owning side: joint and Client-1-owned go left,
    # Client-2-owned go right.
    left_accounts = [row for row in ctx.non_retirement if row.owner.value != "CLIENT2"]
    right_accounts = [row for row in ctx.non_retirement if row.owner.value == "CLIENT2"]

    # Edge-anchored NON RETIREMENT labels at the top of the zone.
    # Rendered in solid black (per reference) so they read as body copy
    # rather than chrome. Only shown on sides that actually have
    # accounts.
    label_y = layout["non_ret_zone_top_y"]
    canvas.setFillColor((0, 0, 0))
    canvas.setFont(FONT_REGULAR, 7.5)
    if left_accounts:
        canvas.drawString(45, label_y, "NON")
        canvas.drawString(45, label_y - 10, "RETIREMENT")
    if right_accounts:
        canvas.drawRightString(PAGE_WIDTH - 45, label_y, "NON")
        canvas.drawRightString(PAGE_WIDTH - 45, label_y - 10, "RETIREMENT")

    def _split(accounts):
        n = len(accounts)
        half = n // 2
        return accounts[:half], accounts[half:]

    def _draw_column(col_x, rows):
        for i, row in enumerate(rows):
            cy = top_y - i * stack_delta
            _draw_non_retirement_bubble(canvas, col_x, cy, r, row)

    left_outer, left_inner = _split(left_accounts)
    right_outer, right_inner = _split(right_accounts)
    _draw_column(outer_l, left_outer)
    _draw_column(inner_l, left_inner)
    _draw_column(inner_r, right_inner)
    _draw_column(outer_r, right_outer)

    # Trust in the center of the non-retirement zone.
    trust_row = ctx.trust[0] if ctx.trust else None
    tx = layout["trust_x"]
    ty = layout["trust_y"]
    tr = layout["trust_r"]
    draw_filled_circle(canvas, tx, ty, tr, fill=(1, 1, 1), stroke=GRAY_400)
    trust_label = ctx.client.trust_label or "Family Trust"
    lines = _wrap(trust_label, 20)[:3]
    for i, line in enumerate(lines):
        draw_centered_text(
            canvas, tx, ty + 18 - i * 10, line, font=FONT_BOLD, size=9, color=GRAY_800
        )
    trust_balance = trust_row.balance.balance if trust_row else Decimal("0")
    draw_centered_text(
        canvas, tx, ty - 12, money(trust_balance), font=FONT_BOLD, size=11, color=GRAY_800
    )
    if trust_row and trust_row.balance.as_of_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 7)
        canvas.drawCentredString(
            tx, ty - 28, f"a/o {trust_row.balance.as_of_date.strftime('%m/%d/%y')}"
        )


def _draw_non_retirement_bubble(canvas: Canvas, cx: float, cy: float, r: float, row) -> None:
    """Non-retirement account bubble. Labels wrap to 2 lines so long
    names like "Wells Fargo Main Checking" or "Pinnacle Private Reserve"
    render in full — matching the reference sample."""
    draw_filled_circle(canvas, cx, cy, r, fill=(1, 1, 1), stroke=GRAY_400)
    raw_label = row.account.display_name or row.account.kind.value.replace("_", " ").title()
    label_lines = _wrap(raw_label, 13)[:2]

    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 6.5)
    canvas.drawCentredString(cx, cy + r - 8, "ACCT #")
    canvas.setFont(FONT_BOLD, 7)
    for i, line in enumerate(label_lines):
        canvas.drawCentredString(cx, cy + r - 17 - i * 8, line)

    amount = money(row.balance.balance)
    if row.balance.is_stale:
        amount += " *"
    canvas.setFillColor(STALE_RED if row.balance.is_stale else GRAY_800)
    canvas.setFont(FONT_BOLD, 8)
    canvas.drawCentredString(cx, cy - 8, amount)

    if row.balance.as_of_date:
        canvas.setFillColor(GRAY_600)
        canvas.setFont(FONT_REGULAR, 6.5)
        canvas.drawCentredString(cx, cy - 18, f"a/o {row.balance.as_of_date.strftime('%m/%d/%y')}")


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
    """Bottom liabilities table.

    Silver/gray filled rectangle with "Liabilities:" header rendered
    INSIDE the box at the top — matches the reference sample. Rows are
    itemized below the header inside the same rectangle.
    """
    if not ctx.liabilities:
        return
    layout = TCC_LAYOUT
    w = layout["liab_table_w"]
    x = CENTER_X - w / 2
    y = layout["liab_table_y"]

    header_h = 16
    row_h = 12
    total_h = header_h + len(ctx.liabilities) * row_h + 8

    # Silver background rectangle covering both the header and the rows.
    canvas.saveState()
    canvas.setFillColor(GRAY_100)
    canvas.setStrokeColor(GRAY_400)
    canvas.setLineWidth(0.5)
    canvas.rect(x, y, w, total_h, fill=1, stroke=1)
    canvas.restoreState()

    # "Liabilities:" header inside the box, at the top.
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 9)
    canvas.drawCentredString(x + w / 2, y + total_h - 12, "Liabilities:")

    # Optional thin separator between header and rows.
    canvas.setStrokeColor(GRAY_400)
    canvas.setLineWidth(0.4)
    canvas.line(x + 6, y + total_h - header_h, x + w - 6, y + total_h - header_h)

    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 8)
    for i, row in enumerate(ctx.liabilities):
        row_y = y + total_h - header_h - 10 - i * row_h
        canvas.drawString(x + 10, row_y, row.liability.label)
        canvas.drawRightString(x + w - 10, row_y, money(row.balance.balance))


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
    """Red stale-info notice, wrapped in a thin black rectangle (matches
    the reference sample)."""
    if not totals.stale_present:
        return
    text = "* Indicates we do not have up to date information"
    canvas.setFont(FONT_REGULAR, FOOTNOTE_SIZE)
    text_w = canvas.stringWidth(text, FONT_REGULAR, FOOTNOTE_SIZE)
    pad_x = 6
    pad_y = 4
    box_w = text_w + pad_x * 2
    box_h = FOOTNOTE_SIZE + pad_y * 2
    y = TCC_LAYOUT["stale_footnote_y"]
    x = PAGE_WIDTH - 45 - box_w

    canvas.saveState()
    canvas.setStrokeColor((0, 0, 0))
    canvas.setLineWidth(0.6)
    canvas.rect(x, y - pad_y, box_w, box_h, fill=0, stroke=1)
    canvas.restoreState()

    canvas.setFillColor(STALE_RED)
    canvas.drawString(x + pad_x, y, text)


def _draw_footer(canvas: Canvas, report: Report) -> None:
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawString(45, 20, f"AW Client Portal · {report.client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 45, 20, "TCC · Page 1 of 1")


# Backwards-compat: keep the old symbol name so external imports don't break.
_ = OUTFLOW_RED, BRAND_BLUE, AccountSection  # keep imports referenced
