"""SACS (Simple Automated Cash Flow System) PDF generator.

Two pages, fully fixed layout — reference targets are ``assets/`` images
image-f1a8b7f4 (Page 1) and image-e44a66e5 (Page 2).

Every position lives in ``SACS_LAYOUT`` so tuning is a matter of adjusting
a single dict entry, not chasing calls throughout the module.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from app.models import Report
from app.pdf.common import (
    draw_arrow_polygon,
    draw_centered_text,
    draw_dashed_line,
    draw_filled_circle,
    draw_pill,
    money,
)
from app.pdf.theme import (
    BRAND_BLUE,
    BRAND_BLUE_DARK,
    BRAND_BLUE_LIGHT,
    FONT_BOLD,
    FONT_REGULAR,
    GRAY_400,
    GRAY_600,
    GRAY_800,
    INFLOW_GREEN,
    LABEL_SIZE,
    OUTFLOW_RED,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PRIVATE_RESERVE_BLUE,
    SUBTITLE_SIZE,
    TITLE_SIZE,
)
from app.reports.services import ReportTotals, totals_from_report

# Every measurement is in PDF points (1pt = 1/72"). Portrait US Letter.
CENTER_X = PAGE_WIDTH / 2

SACS_LAYOUT = {
    "title_y": PAGE_HEIGHT - 60,
    "subtitle_y": PAGE_HEIGHT - 82,
    "salary_x": 70,
    "salary_top_y": PAGE_HEIGHT - 120,
    "dollar_icon": (52, PAGE_HEIGHT - 100),
    "annotation_x": PAGE_WIDTH - 120,
    "annotation_y": PAGE_HEIGHT - 140,
    # Circle geometry
    "circle_radius": 78,
    "inflow_center": (168, 480),
    "outflow_center": (444, 480),
    "reserve_center": (CENTER_X, 260),
    # Arrows
    "into_inflow_start": (168, PAGE_HEIGHT - 130),
    "into_inflow_end": (168, 480 + 78 + 4),
    "inflow_to_outflow_start": (168 + 78 + 4, 480),
    "inflow_to_outflow_end": (444 - 78 - 4, 480),
    "inflow_to_reserve_start": (168, 480 - 78 - 4),
    "inflow_to_reserve_end": (CENTER_X - 40, 260 + 78 + 4),
    # Bottom label
    "monthly_cashflow_y": 90,
    "divider_top": 40,
    "divider_bottom": 20,
    # Page 2
    "p2_title_y": PAGE_HEIGHT - 100,
    "p2_divider_top": PAGE_HEIGHT - 60,
    "p2_divider_bottom": 60,
    "p2_fica_center": (CENTER_X - 130, 440),
    "p2_investment_center": (CENTER_X + 130, 440),
    "p2_circle_radius": 90,
}


# ---------------------------------------------------------------------------- render


def render_sacs(report: Report, output_path: str | Path | BytesIO | None = None) -> bytes:
    """Build the SACS PDF for ``report`` and return the bytes.

    If ``output_path`` is a str/Path, also writes to disk.
    """
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    canvas.setTitle(f"SACS · {report.client.display_name} · {report.meeting_date.isoformat()}")
    canvas.setAuthor("AW Client Portal")

    totals = totals_from_report(report)

    _render_page1(canvas, report, totals)
    canvas.showPage()
    _render_page2(canvas, report, totals)

    canvas.save()
    data = buffer.getvalue()

    if isinstance(output_path, (str, Path)):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
    return data


# ---------------------------------------------------------------------------- page 1


def _render_page1(canvas: Canvas, report: Report, totals: ReportTotals) -> None:
    client = report.client

    # ---- Header ----
    draw_centered_text(
        canvas,
        CENTER_X,
        SACS_LAYOUT["title_y"],
        "Simple Automated Cashflow System (SACS)",
        font=FONT_BOLD,
        size=TITLE_SIZE,
        color=GRAY_800,
    )
    draw_centered_text(
        canvas,
        CENTER_X,
        SACS_LAYOUT["subtitle_y"],
        f"{client.display_name} — {report.meeting_date.strftime('%B %d, %Y')}",
        font=FONT_REGULAR,
        size=SUBTITLE_SIZE,
        color=GRAY_600,
    )

    # ---- $ icon (top-left) drawn as a stylized character ----
    dx, dy = SACS_LAYOUT["dollar_icon"]
    canvas.setFillColor(INFLOW_GREEN)
    canvas.setFont(FONT_BOLD, 40)
    canvas.drawString(dx, dy, "$")

    # ---- Salary lines beneath $ icon ----
    canvas.setFillColor(INFLOW_GREEN)
    canvas.setFont(FONT_BOLD, 10)
    salary_x = SACS_LAYOUT["salary_x"]
    salary_y = SACS_LAYOUT["salary_top_y"]
    if client.c1_monthly_salary:
        canvas.drawString(
            salary_x,
            salary_y,
            f"{money(client.c1_monthly_salary, with_cents=False)} - {client.c1_first}",
        )
    if client.is_married and client.c2_monthly_salary:
        canvas.drawString(
            salary_x,
            salary_y - 14,
            f"{money(client.c2_monthly_salary, with_cents=False)} - {client.c2_first}",
        )

    # ---- Top-right annotation "X = Monthly Expenses" ----
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 9)
    canvas.drawRightString(
        SACS_LAYOUT["annotation_x"] + 100,
        SACS_LAYOUT["annotation_y"],
        "X = Monthly Expenses",
    )

    # ---- Green down-arrow into Inflow ----
    draw_arrow_polygon(
        canvas,
        SACS_LAYOUT["into_inflow_start"],
        SACS_LAYOUT["into_inflow_end"],
        fill=INFLOW_GREEN,
    )

    # ---- INFLOW circle ----
    ix, iy = SACS_LAYOUT["inflow_center"]
    r = SACS_LAYOUT["circle_radius"]
    draw_filled_circle(canvas, ix, iy, r, fill=INFLOW_GREEN)
    draw_centered_text(canvas, ix, iy + 22, "INFLOW", font=FONT_BOLD, size=14, color=(1, 1, 1))
    draw_pill(canvas, ix, iy - 4, 100, 22, fill=(1, 1, 1), stroke=(0.9, 0.9, 0.9))
    draw_centered_text(
        canvas,
        ix,
        iy - 10,
        money(totals.inflow, with_cents=False),
        font=FONT_BOLD,
        size=13,
        color=GRAY_800,
    )
    # $1,000 Floor label along the bottom edge of the circle
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawCentredString(ix, iy - r + 6, "$1,000 Floor")
    # thin baseline
    canvas.setStrokeColor(GRAY_800)
    canvas.setLineWidth(0.5)
    canvas.line(ix - r + 12, iy - r + 18, ix + r - 12, iy - r + 18)

    # ---- Red right-arrow to Outflow, labeled ----
    outflow_label = f"X = {money(totals.outflow, with_cents=False)}/month*"
    draw_arrow_polygon(
        canvas,
        SACS_LAYOUT["inflow_to_outflow_start"],
        SACS_LAYOUT["inflow_to_outflow_end"],
        fill=OUTFLOW_RED,
        stroke=(0.5, 0.15, 0.15),
        label=outflow_label,
        label_size=9,
        label_color=OUTFLOW_RED,
    )
    # sub-label
    mid_x = (
        SACS_LAYOUT["inflow_to_outflow_start"][0] + SACS_LAYOUT["inflow_to_outflow_end"][0]
    ) / 2
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawCentredString(mid_x, 480 - 22, "Automated transfer on the 28th")

    # ---- OUTFLOW circle ----
    ox, oy = SACS_LAYOUT["outflow_center"]
    draw_filled_circle(canvas, ox, oy, r, fill=OUTFLOW_RED)
    draw_centered_text(canvas, ox, oy + 22, "OUTFLOW", font=FONT_BOLD, size=14, color=(1, 1, 1))
    draw_pill(canvas, ox, oy - 4, 100, 22, fill=(1, 1, 1), stroke=(0.9, 0.9, 0.9))
    draw_centered_text(
        canvas,
        ox,
        oy - 10,
        money(totals.outflow, with_cents=False),
        font=FONT_BOLD,
        size=13,
        color=GRAY_800,
    )
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawCentredString(ox, oy - r + 6, "$1,000 Floor")
    canvas.setStrokeColor(GRAY_800)
    canvas.line(ox - r + 12, oy - r + 18, ox + r - 12, oy - r + 18)

    # ---- Blue diagonal arrow to Private Reserve ----
    excess_label = f"{money(totals.excess, with_cents=False)}/mo*"
    draw_arrow_polygon(
        canvas,
        SACS_LAYOUT["inflow_to_reserve_start"],
        SACS_LAYOUT["inflow_to_reserve_end"],
        fill=BRAND_BLUE_LIGHT,
        stroke=BRAND_BLUE,
        label=excess_label,
        label_size=9,
        label_color=BRAND_BLUE,
    )

    # ---- PRIVATE RESERVE circle ----
    px, py = SACS_LAYOUT["reserve_center"]
    draw_filled_circle(canvas, px, py, r, fill=PRIVATE_RESERVE_BLUE)
    # Two-line label (matches sample)
    draw_centered_text(canvas, px, py + 16, "PRIVATE", font=FONT_BOLD, size=13, color=(1, 1, 1))
    draw_centered_text(canvas, px, py + 2, "RESERVE", font=FONT_BOLD, size=13, color=(1, 1, 1))
    # PR balance (small, below the "piggy" glyph)
    draw_centered_text(
        canvas, px, py - 30, money(totals.pr_balance), font=FONT_BOLD, size=11, color=(1, 1, 1)
    )

    # ---- MONTHLY CASHFLOW footer + dashed divider ----
    draw_centered_text(
        canvas,
        CENTER_X,
        SACS_LAYOUT["monthly_cashflow_y"],
        "MONTHLY CASHFLOW",
        font=FONT_BOLD,
        size=10,
        color=GRAY_800,
    )
    draw_dashed_line(
        canvas,
        CENTER_X,
        SACS_LAYOUT["divider_top"],
        CENTER_X,
        SACS_LAYOUT["divider_bottom"],
        color=GRAY_400,
        width=1,
        dash=(3, 3),
    )

    # Footer with client label
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(36, 24, f"AW Client Portal · {client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 36, 24, "Page 1 of 2")


# ---------------------------------------------------------------------------- page 2


def _render_page2(canvas: Canvas, report: Report, totals: ReportTotals) -> None:
    client = report.client

    # Continuation dashed divider at top
    draw_dashed_line(
        canvas,
        CENTER_X,
        SACS_LAYOUT["p2_divider_top"],
        CENTER_X,
        SACS_LAYOUT["p2_divider_bottom"],
        color=GRAY_400,
        width=1,
        dash=(3, 3),
    )

    # Title
    draw_centered_text(
        canvas,
        CENTER_X,
        SACS_LAYOUT["p2_title_y"],
        "Simple Automated Cashflow System (SACS)",
        font=FONT_BOLD,
        size=TITLE_SIZE,
        color=GRAY_800,
    )

    r = SACS_LAYOUT["p2_circle_radius"]

    # Left: light-blue PR circle. Label must match Page 1 exactly.
    fx, fy = SACS_LAYOUT["p2_fica_center"]
    draw_filled_circle(canvas, fx, fy, r, fill=BRAND_BLUE_LIGHT, stroke=BRAND_BLUE)
    label_lines = client.private_reserve_label.upper().split()
    if len(label_lines) == 1:
        draw_centered_text(
            canvas, fx, fy + 16, label_lines[0], font=FONT_BOLD, size=15, color=GRAY_800
        )
    else:
        draw_centered_text(
            canvas, fx, fy + 22, label_lines[0], font=FONT_BOLD, size=13, color=GRAY_800
        )
        draw_centered_text(
            canvas, fx, fy + 6, " ".join(label_lines[1:]), font=FONT_BOLD, size=13, color=GRAY_800
        )

    # Balance pill inside the circle
    draw_pill(canvas, fx, fy - 18, 120, 24, fill=(1, 1, 1), stroke=(0.8, 0.85, 0.9))
    draw_centered_text(
        canvas, fx, fy - 24, money(totals.pr_balance), font=FONT_BOLD, size=13, color=GRAY_800
    )

    # Caption + target under FICA circle
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, LABEL_SIZE)
    canvas.drawCentredString(fx, fy - r - 14, "6X Monthly Expenses + Deductibles")
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawCentredString(fx, fy - r - 30, f"Target: {money(totals.pr_target)}")

    # Right: dark-blue INVESTMENT circle
    ix, iy = SACS_LAYOUT["p2_investment_center"]
    draw_filled_circle(canvas, ix, iy, r, fill=BRAND_BLUE_DARK)
    draw_centered_text(canvas, ix, iy + 22, "INVESTMENT", font=FONT_BOLD, size=13, color=(1, 1, 1))
    draw_centered_text(canvas, ix, iy + 6, "ACCOUNT", font=FONT_BOLD, size=13, color=(1, 1, 1))
    draw_pill(canvas, ix, iy - 18, 120, 24, fill=(1, 1, 1), stroke=(0.6, 0.65, 0.7))
    remainder_display = money(totals.investment_balance)
    if totals.investment_balance and totals.investment_balance > Decimal("0"):
        remainder_display += "+"
    draw_centered_text(
        canvas, ix, iy - 24, remainder_display, font=FONT_BOLD, size=13, color=GRAY_800
    )
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, LABEL_SIZE)
    canvas.drawCentredString(ix, iy - r - 14, "Remainder")

    # Double-headed arrow between the two circles
    arrow_y = fy
    left_x = fx + r + 6
    right_x = ix - r - 6
    # Right-pointing shaft
    draw_arrow_polygon(
        canvas,
        (left_x, arrow_y),
        ((left_x + right_x) / 2, arrow_y),
        fill=BRAND_BLUE,
        shaft_width=10,
        head_length=12,
        head_width=20,
    )
    # Left-pointing shaft
    draw_arrow_polygon(
        canvas,
        (right_x, arrow_y),
        ((left_x + right_x) / 2, arrow_y),
        fill=BRAND_BLUE,
        shaft_width=10,
        head_length=12,
        head_width=20,
    )

    # Footer
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(36, 24, f"AW Client Portal · {client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 36, 24, "Page 2 of 2")
