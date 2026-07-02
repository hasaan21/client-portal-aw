"""Coordinates PDF generation for a finalized report.

Writes SACS + TCC PDFs into ``PDF_OUTPUT_DIR / <report_id> /`` and stamps the
paths back onto the Report row. Idempotent: re-finalizing overwrites in place.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from flask import current_app

from app.models import Report


def _output_dir_for(report: Report) -> Path:
    root = Path(current_app.config["PDF_OUTPUT_DIR"])
    d = root / str(report.id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(client_name: str, meeting_date: date) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in client_name)
    return f"{safe}-{meeting_date.isoformat()}"


def generate_all(report: Report) -> dict[str, str]:
    """Generate every available PDF for a report. Returns a mapping of
    ``{'sacs': path, 'tcc': path}``. Only kinds that have a builder are
    included."""
    outputs: dict[str, str] = {}
    out_dir = _output_dir_for(report)
    slug = _slug(report.client.display_name, report.meeting_date)

    # SACS (M4) ---------------------------------------------------------
    try:
        from app.pdf.sacs import render_sacs

        sacs_path = out_dir / f"SACS-{slug}.pdf"
        render_sacs(report, sacs_path)
        outputs["sacs"] = str(sacs_path)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("SACS render failed: %s", exc)

    # TCC (M5) ---------------------------------------------------------
    try:
        from app.pdf.tcc import render_tcc

        tcc_path = out_dir / f"TCC-{slug}.pdf"
        render_tcc(report, tcc_path)
        outputs["tcc"] = str(tcc_path)
    except ImportError:
        # TCC builder ships in M5.
        pass
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("TCC render failed: %s", exc)

    return outputs
