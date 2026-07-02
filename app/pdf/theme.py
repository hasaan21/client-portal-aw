"""Shared PDF constants: colors, fonts, page geometry.

Referenced by both SACS (M4) and TCC (M5) builders. Numbers here map to the
screenshots saved in ``assets/`` so tweaking a single value here keeps both
report types visually consistent.
"""

from __future__ import annotations

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import LETTER

# ---- Page geometry -----------------------------------------------------------

PAGE_SIZE = LETTER  # (612, 792) points
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
MARGIN = 36  # 0.5"

# ---- Palette (matches the samples in assets/) --------------------------------

BRAND_BLUE = Color(0.12, 0.32, 0.62)  # header/footer accents
BRAND_BLUE_DARK = Color(0.09, 0.20, 0.40)  # Investment Account (dark navy)
BRAND_BLUE_LIGHT = Color(0.68, 0.82, 0.92)  # FICA / Private Reserve page 2

INFLOW_GREEN = Color(0.28, 0.66, 0.36)
OUTFLOW_RED = Color(0.82, 0.24, 0.24)
PRIVATE_RESERVE_BLUE = Color(0.28, 0.47, 0.72)

CLIENT_OVAL_GREEN = Color(0.52, 0.73, 0.45)
CLIENT_OVAL_STROKE = Color(0.15, 0.35, 0.15)

GRAY_50 = Color(0.97, 0.97, 0.97)
GRAY_100 = Color(0.93, 0.93, 0.94)
GRAY_200 = Color(0.86, 0.86, 0.87)
GRAY_400 = Color(0.62, 0.62, 0.64)
GRAY_600 = Color(0.42, 0.42, 0.44)
GRAY_800 = Color(0.20, 0.20, 0.22)

STALE_RED = Color(0.82, 0.20, 0.20)

# ---- Typography --------------------------------------------------------------

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

TITLE_SIZE = 18
SUBTITLE_SIZE = 12
LABEL_SIZE = 9
BUBBLE_TITLE_SIZE = 9
BUBBLE_AMOUNT_SIZE = 10
FOOTNOTE_SIZE = 8
