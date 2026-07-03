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

from reportlab.lib.colors import Color
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
    # Runs all the way to y=0 (the page's bottom edge) so it visually
    # connects to page 2's divider when the report is stacked/scrolled.
    "divider_bottom": 0,
    # Page 2
    "p2_title_y": PAGE_HEIGHT - 100,
    # Starts at the very top of the page so it visually meets page 1's
    # bottom divider when scrolled continuously.
    "p2_divider_top": PAGE_HEIGHT,
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

    if isinstance(output_path, str | Path):
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

    # ---- "X = Monthly Expenses" annotation + papers icon ----
    # Group them: the papers icon sits DIRECTLY ABOVE the label, so both
    # read as a single caption cluster in the right column next to
    # OUTFLOW (matching the reference sample where the "receipts" icon
    # is right next to the annotation).
    outflow_cx = SACS_LAYOUT["outflow_center"][0]
    outflow_cy = SACS_LAYOUT["outflow_center"][1]
    r = SACS_LAYOUT["circle_radius"]

    ann_x = PAGE_WIDTH - 55
    pill_y = outflow_cy - 6  # OUTFLOW pill vertical band
    ann_y = pill_y + 20  # sits just above the horizontal leader

    # Papers icon: centered on ann_x, resting just above the annotation.
    _draw_papers_icon(canvas, ann_x - 13, ann_y + 22)

    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 9)
    canvas.drawCentredString(ann_x, ann_y + 6, "X = Monthly")
    canvas.drawCentredString(ann_x, ann_y - 6, "Expenses")

    canvas.setStrokeColor(GRAY_600)
    canvas.setLineWidth(0.6)
    # Horizontal leader from OUTFLOW's right edge to a corner under the label,
    # then a short vertical rise into the label baseline.
    canvas.line(outflow_cx + r + 2, pill_y, ann_x, pill_y)  # horizontal right
    canvas.line(outflow_cx + r + 2, pill_y, outflow_cx + r + 8, pill_y + 3)
    canvas.line(outflow_cx + r + 2, pill_y, outflow_cx + r + 8, pill_y - 3)
    canvas.line(ann_x, pill_y, ann_x, ann_y - 14)

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
    _draw_floor_line(canvas, ix, iy, r)

    # ---- Red hollow arrow to Outflow (label INSIDE the shaft) ----
    outflow_label = f"X = {money(totals.outflow, with_cents=False)}/month*"
    draw_arrow_polygon(
        canvas,
        SACS_LAYOUT["inflow_to_outflow_start"],
        SACS_LAYOUT["inflow_to_outflow_end"],
        fill=None,
        stroke=OUTFLOW_RED,
        stroke_width=1.4,
        shaft_width=24,  # thicker so label fits inside
        head_length=22,
        head_width=36,
        label=outflow_label,
        label_size=9,
        label_color=OUTFLOW_RED,
        label_inside=True,
    )
    # sub-label under the arrow
    mid_x = (
        SACS_LAYOUT["inflow_to_outflow_start"][0] + SACS_LAYOUT["inflow_to_outflow_end"][0]
    ) / 2
    canvas.setFillColor(GRAY_600)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawCentredString(mid_x, 480 - 26, "Automated transfer on the 28th")

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
    _draw_floor_line(canvas, ox, oy, r)

    # ---- Blue L-shaped hollow arrow: DOWN from INFLOW, RIGHT into PR ----
    # Vertical shaft drops from below the INFLOW $1,000 Floor down to the
    # PR center's Y, then the horizontal shaft runs right into the left
    # edge of the PRIVATE RESERVE circle.
    excess_label = f"{money(totals.excess, with_cents=False)}/mo*"
    px, py = SACS_LAYOUT["reserve_center"]
    _draw_l_arrow_down_right(
        canvas,
        top=(ix, iy - r - 6),  # a few pt below the INFLOW circle
        corner=(ix, py),
        tip_x=px - r - 4,
        shaft_width=22,
        head_length=22,
        head_width=34,
        stroke=BRAND_BLUE,
        stroke_width=1.4,
        label=excess_label,
        label_size=9,
        label_color=BRAND_BLUE,
    )

    # ---- PRIVATE RESERVE circle ----
    px, py = SACS_LAYOUT["reserve_center"]
    draw_filled_circle(canvas, px, py, r, fill=PRIVATE_RESERVE_BLUE)
    # Two-line label (matches sample)
    draw_centered_text(canvas, px, py + 34, "PRIVATE", font=FONT_BOLD, size=13, color=(1, 1, 1))
    draw_centered_text(canvas, px, py + 20, "RESERVE", font=FONT_BOLD, size=13, color=(1, 1, 1))
    # Piggy bank illustration (centered slightly below the label)
    _draw_piggy_bank(canvas, px, py - 12, scale=0.85)
    # PR balance (small, at the bottom of the circle)
    draw_centered_text(
        canvas, px, py - 50, money(totals.pr_balance), font=FONT_BOLD, size=11, color=(1, 1, 1)
    )

    # ---- Blue dashed divider from PR bottom → footer → off-page ----
    # Runs UP into the bottom of the PRIVATE RESERVE circle and DOWN past
    # the "MONTHLY | CASHFLOW" band, so it visually anchors the whole
    # column. The MONTHLY CASHFLOW words are split so the divider passes
    # cleanly between them.
    _pr_x, pr_y = SACS_LAYOUT["reserve_center"]
    divider_top = pr_y - r  # PR circle bottom edge
    monthly_y = SACS_LAYOUT["monthly_cashflow_y"]
    draw_dashed_line(
        canvas,
        CENTER_X,
        divider_top,
        CENTER_X,
        monthly_y + 6,
        color=BRAND_BLUE,
        width=1,
        dash=(3, 3),
    )
    draw_dashed_line(
        canvas,
        CENTER_X,
        monthly_y - 6,
        CENTER_X,
        SACS_LAYOUT["divider_bottom"],
        color=BRAND_BLUE,
        width=1,
        dash=(3, 3),
    )

    # "MONTHLY | CASHFLOW" text with a divider-shaped gap in the middle.
    canvas.setFillColor(GRAY_800)
    canvas.setFont(FONT_BOLD, 11)
    canvas.drawRightString(CENTER_X - 6, monthly_y - 3, "MONTHLY")
    canvas.drawString(CENTER_X + 6, monthly_y - 3, "CASHFLOW")

    # Footer with client label
    canvas.setFillColor(GRAY_400)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawString(36, 24, f"AW Client Portal · {client.display_name}")
    canvas.drawRightString(PAGE_WIDTH - 36, 24, "Page 1 of 2")


# ---------------------------------------------------------------------------- L-shaped arrow


def _draw_l_arrow_down_right(
    canvas: Canvas,
    top: tuple[float, float],
    corner: tuple[float, float],
    tip_x: float,
    shaft_width: float = 22,
    head_length: float = 20,
    head_width: float = 34,
    stroke: Color | None = None,
    stroke_width: float = 1.4,
    fill: Color | None = None,
    label: str | None = None,
    label_font: str = FONT_BOLD,
    label_size: float = 9,
    label_color: Color | None = None,
) -> None:
    """Hollow L-shaped arrow that runs DOWN from ``top`` to ``corner``
    and then RIGHT to a triangular head whose tip is at ``(tip_x,
    corner.y)``.

    All coordinates are in canvas points. The arrow is drawn as one
    outlined polygon so the inner corner is clean.
    """
    sx, sy = top
    _corner_x, cy = corner
    w = shaft_width / 2
    hw = head_width / 2

    # Head starts head_length before the tip
    head_base_x = tip_x - head_length

    # Outline path (counter-clockwise from top-left):
    #  1  top-left of vertical shaft
    #  2  top-right of vertical shaft (right)
    #  3  down to inner corner (right edge of vertical = top edge of horizontal)
    #  4  right along top of horizontal to head base
    #  5  up to head-top-base
    #  6  out to tip
    #  7  down to head-bottom-base
    #  8  left back to under the outer corner (bottom of horizontal)
    #  9  left along bottom of horizontal to outer corner
    # 10  up along left of vertical, close
    p = canvas.beginPath()
    p.moveTo(sx - w, sy)
    p.lineTo(sx + w, sy)
    p.lineTo(sx + w, cy + w)
    p.lineTo(head_base_x, cy + w)
    p.lineTo(head_base_x, cy + hw)
    p.lineTo(tip_x, cy)
    p.lineTo(head_base_x, cy - hw)
    p.lineTo(head_base_x, cy - w)
    p.lineTo(sx - w, cy - w)
    p.lineTo(sx - w, sy)
    p.close()

    canvas.saveState()
    do_fill = fill is not None
    if do_fill:
        canvas.setFillColor(fill)
    if stroke is not None:
        canvas.setStrokeColor(stroke)
    canvas.setLineWidth(stroke_width)
    canvas.drawPath(p, fill=1 if do_fill else 0, stroke=1 if stroke else 0)
    canvas.restoreState()

    if label:
        # Centered on the horizontal segment, between the vertical shaft
        # right-edge and the head base.
        lx = (sx + w + head_base_x) / 2
        ly = cy - label_size / 3
        draw_centered_text(
            canvas, lx, ly, label, font=label_font, size=label_size, color=label_color
        )


# ---------------------------------------------------------------------------- decorative glyphs


def _draw_floor_line(canvas: Canvas, cx: float, cy: float, r: float) -> None:
    """Prominent "$1,000 Floor" indicator inside INFLOW/OUTFLOW circles.

    Line stays fully inside the circle (chord ~ 24pt inset from the edge),
    is drawn thicker than before, and the label is set in bold so it
    reads clearly against the strongly-saturated fill.
    """
    # Chord y-position: about 22pt above the bottom of the circle so the
    # line is clearly INSIDE the circle rather than tangent to its edge.
    line_y = cy - r + 22
    # Chord width: use the circle's math (a chord at height h above center
    # has half-length sqrt(r^2 - h^2)); here h = r - 22.
    h = r - 22
    half = (r * r - h * h) ** 0.5 - 6  # 6pt inset from the circle edge
    canvas.saveState()
    canvas.setStrokeColor((0, 0, 0))
    canvas.setLineWidth(1.2)
    canvas.line(cx - half, line_y, cx + half, line_y)
    canvas.setFillColor((0, 0, 0))
    canvas.setFont(FONT_BOLD, 10)
    canvas.drawCentredString(cx, line_y - 12, "$1,000 Floor")
    canvas.restoreState()


def _draw_papers_icon(canvas: Canvas, x: float, y: float) -> None:
    """Small stack-of-documents glyph rendered from primitives.

    Draws three overlapping rounded rectangles + a few horizontal lines
    to suggest text, matching the paper icon in the SACS reference.
    """
    canvas.saveState()
    # Back sheet
    canvas.setFillColor((0.88, 0.88, 0.90))
    canvas.setStrokeColor(GRAY_600)
    canvas.setLineWidth(0.5)
    canvas.roundRect(x + 4, y + 6, 26, 30, 2, fill=1, stroke=1)
    # Middle sheet
    canvas.setFillColor((0.94, 0.94, 0.96))
    canvas.roundRect(x + 2, y + 3, 26, 30, 2, fill=1, stroke=1)
    # Front sheet
    canvas.setFillColor((1, 1, 1))
    canvas.roundRect(x, y, 26, 30, 2, fill=1, stroke=1)
    # Text lines on front sheet
    canvas.setStrokeColor(GRAY_400)
    canvas.setLineWidth(0.4)
    for i in range(4):
        line_y = y + 24 - i * 5
        canvas.line(x + 4, line_y, x + 22, line_y)
    canvas.restoreState()


def _draw_piggy_bank(canvas: Canvas, cx: float, cy: float, scale: float = 1.0) -> None:
    """Stylized pink piggy bank rendered from primitives, centered at
    ``(cx, cy)``. Sized in ~40pt tall units when ``scale == 1.0``."""
    canvas.saveState()
    pink = (0.98, 0.78, 0.80)
    dark_pink = (0.85, 0.55, 0.60)
    # Body — main oval (drawn as circle scaled horizontally via ellipse)
    canvas.setFillColor(pink)
    canvas.setStrokeColor(dark_pink)
    canvas.setLineWidth(0.6)
    body_w = 30 * scale
    body_h = 22 * scale
    canvas.ellipse(cx - body_w, cy - body_h, cx + body_w, cy + body_h, fill=1, stroke=1)
    # Ear (triangle)
    ear = canvas.beginPath()
    ear.moveTo(cx - body_w * 0.6, cy + body_h * 0.7)
    ear.lineTo(cx - body_w * 0.35, cy + body_h * 1.1)
    ear.lineTo(cx - body_w * 0.2, cy + body_h * 0.6)
    ear.close()
    canvas.drawPath(ear, fill=1, stroke=1)
    # Snout
    snout_w = 8 * scale
    snout_h = 6 * scale
    canvas.setFillColor(dark_pink)
    canvas.ellipse(
        cx - body_w - snout_w,
        cy - snout_h,
        cx - body_w + snout_w * 0.4,
        cy + snout_h,
        fill=1,
        stroke=1,
    )
    # Nostrils
    canvas.setFillColor((0.4, 0.2, 0.25))
    canvas.circle(cx - body_w - snout_w * 0.4, cy + 1, 0.8 * scale, fill=1, stroke=0)
    canvas.circle(cx - body_w - snout_w * 0.4, cy - 2, 0.8 * scale, fill=1, stroke=0)
    # Eye
    canvas.setFillColor((0.15, 0.10, 0.15))
    canvas.circle(cx - body_w * 0.55, cy + body_h * 0.35, 1.2 * scale, fill=1, stroke=0)
    # Coin slot on top
    canvas.setFillColor((0.4, 0.2, 0.25))
    canvas.rect(cx - 5 * scale, cy + body_h - 1, 10 * scale, 1.6 * scale, fill=1, stroke=0)
    # Front legs
    canvas.setFillColor(pink)
    canvas.setStrokeColor(dark_pink)
    canvas.rect(cx - body_w * 0.6, cy - body_h - 4 * scale, 5 * scale, 5 * scale, fill=1, stroke=1)
    canvas.rect(cx + body_w * 0.3, cy - body_h - 4 * scale, 5 * scale, 5 * scale, fill=1, stroke=1)
    canvas.restoreState()


# ---------------------------------------------------------------------------- page 2


def _render_page2(canvas: Canvas, report: Report, totals: ReportTotals) -> None:
    client = report.client

    # Continuation dashed divider from page 1. Runs from the very top of
    # the page all the way down to the double-headed arrow, with a small
    # gap only around the title text so it doesn't visually collide.
    arrow_y = SACS_LAYOUT["p2_fica_center"][1]
    title_y = SACS_LAYOUT["p2_title_y"]
    # Segment 1: page top → just above the title band
    draw_dashed_line(
        canvas,
        CENTER_X,
        SACS_LAYOUT["p2_divider_top"],
        CENTER_X,
        title_y + 8,
        color=BRAND_BLUE,
        width=1,
        dash=(3, 3),
    )
    # Segment 2: just below the title band → touching the arrow's edge.
    # The arrow head extends ±(head_width/2)=10pt around arrow_y, so we
    # terminate the dashed line right at the arrow's upper edge so it
    # visually "hands off" into the arrow.
    draw_dashed_line(
        canvas,
        CENTER_X,
        title_y - 10,
        CENTER_X,
        arrow_y + 10,
        color=BRAND_BLUE,
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

    # Double-headed arrow — a single horizontal shaft between the two
    # circles with arrow-heads on BOTH ends pointing OUT into the
    # adjacent circle (left tip into PR, right tip into INVESTMENT).
    arrow_y = fy
    left_x = fx + r + 6
    right_x = ix - r - 6
    mid_x = (left_x + right_x) / 2
    # Left-pointing arrow: base at midpoint, tip pointing INTO PR (left)
    draw_arrow_polygon(
        canvas,
        (mid_x, arrow_y),
        (left_x, arrow_y),
        fill=BRAND_BLUE,
        shaft_width=10,
        head_length=12,
        head_width=20,
    )
    # Right-pointing arrow: base at midpoint, tip pointing INTO INVESTMENT
    draw_arrow_polygon(
        canvas,
        (mid_x, arrow_y),
        (right_x, arrow_y),
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
