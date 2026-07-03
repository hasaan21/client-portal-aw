"""Shared PDF drawing helpers used by both SACS and TCC builders."""

from __future__ import annotations

from decimal import Decimal

from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas

from app.pdf.theme import FONT_BOLD, FONT_REGULAR


def money(value: Decimal | float | int, *, with_cents: bool = True) -> str:
    """Format ``value`` as $12,345.67 (or $12,345 if with_cents=False)."""
    try:
        v = Decimal(str(value))
    except Exception:  # pragma: no cover
        v = Decimal("0")
    if with_cents:
        return f"${v:,.2f}"
    return f"${int(v):,}"


def draw_centered_text(
    canvas: Canvas,
    x: float,
    y: float,
    text: str,
    font: str = FONT_REGULAR,
    size: float = 10,
    color: Color | None = None,
) -> None:
    canvas.setFont(font, size)
    if color is not None:
        canvas.setFillColor(color)
    canvas.drawCentredString(x, y, text)


def draw_filled_circle(
    canvas: Canvas,
    cx: float,
    cy: float,
    r: float,
    fill: Color,
    stroke: Color | None = None,
    stroke_width: float = 0.5,
) -> None:
    canvas.saveState()
    canvas.setFillColor(fill)
    if stroke is not None:
        canvas.setStrokeColor(stroke)
    canvas.setLineWidth(stroke_width)
    canvas.circle(cx, cy, r, stroke=1 if stroke else 0, fill=1)
    canvas.restoreState()


def draw_pill(
    canvas: Canvas,
    cx: float,
    cy: float,
    width: float,
    height: float,
    fill: Color,
    stroke: Color | None = None,
) -> None:
    """A rectangle with rounded ends — used for balance amounts inside circles."""
    canvas.saveState()
    canvas.setFillColor(fill)
    if stroke is not None:
        canvas.setStrokeColor(stroke)
    canvas.roundRect(
        cx - width / 2,
        cy - height / 2,
        width,
        height,
        radius=height / 2,
        fill=1,
        stroke=1 if stroke else 0,
    )
    canvas.restoreState()


def draw_arrow_polygon(
    canvas: Canvas,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: Color | None,
    shaft_width: float = 14,
    head_length: float = 18,
    head_width: float = 26,
    stroke: Color | None = None,
    stroke_width: float = 0.5,
    label: str | None = None,
    label_font: str = FONT_BOLD,
    label_size: float = 9,
    label_color: Color | None = None,
    label_inside: bool = False,
) -> None:
    """Draw a flat 2D arrow (rectangular shaft + triangular head).

    Direction is inferred from start -> end. Works for horizontal, vertical,
    or diagonal directions. Pass ``fill=None`` (with a non-None ``stroke``)
    to render a hollow outline arrow. Set ``label_inside=True`` to place
    the label centered on the shaft (rather than offset perpendicular to
    it).
    """
    import math

    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length  # unit vector along arrow
    px, py = -uy, ux  # perpendicular (left of direction)

    # Shaft goes from start to (head_start) which is head_length before end.
    hx, hy = ex - ux * head_length, ey - uy * head_length

    hw = shaft_width / 2
    p1 = (sx + px * hw, sy + py * hw)
    p2 = (sx - px * hw, sy - py * hw)
    p3 = (hx - px * hw, hy - py * hw)
    p4 = (hx + px * hw, hy + py * hw)

    hd = head_width / 2
    p5 = (hx + px * hd, hy + py * hd)  # head base left
    p6 = (ex, ey)  # tip
    p7 = (hx - px * hd, hy - py * hd)  # head base right

    canvas.saveState()
    do_fill = fill is not None
    if do_fill:
        canvas.setFillColor(fill)
    if stroke is not None:
        canvas.setStrokeColor(stroke)
    elif do_fill:
        canvas.setStrokeColor(fill)
    canvas.setLineWidth(stroke_width)
    path = canvas.beginPath()
    path.moveTo(*p1)
    path.lineTo(*p4)
    path.lineTo(*p5)
    path.lineTo(*p6)
    path.lineTo(*p7)
    path.lineTo(*p3)
    path.lineTo(*p2)
    path.close()
    canvas.drawPath(path, fill=1 if do_fill else 0, stroke=1 if (stroke or do_fill) else 0)
    canvas.restoreState()

    if label:
        mid_x = (sx + hx) / 2
        mid_y = (sy + hy) / 2
        if label_inside:
            # Centered on the shaft (nudged down by ~1/3 the font size to
            # account for text baseline vs visual center).
            lx = mid_x
            ly = mid_y - label_size / 3
        else:
            # Nudged perpendicular so the label sits above the shaft.
            offset = shaft_width / 2 + 6
            lx = mid_x + px * offset
            ly = mid_y + py * offset
        draw_centered_text(
            canvas, lx, ly, label, font=label_font, size=label_size, color=label_color
        )


def draw_dashed_line(
    canvas: Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: Color,
    width: float = 1.0,
    dash: tuple[int, int] = (4, 4),
) -> None:
    canvas.saveState()
    canvas.setStrokeColor(color)
    canvas.setLineWidth(width)
    canvas.setDash(*dash)
    canvas.line(x1, y1, x2, y2)
    canvas.restoreState()


def draw_rounded_box(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: Color,
    stroke: Color | None = None,
    radius: float = 4,
) -> None:
    canvas.saveState()
    canvas.setFillColor(fill)
    if stroke is not None:
        canvas.setStrokeColor(stroke)
    canvas.roundRect(x, y, width, height, radius=radius, fill=1, stroke=1 if stroke else 0)
    canvas.restoreState()
