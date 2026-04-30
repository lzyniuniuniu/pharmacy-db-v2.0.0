"""
Extraction Report
=================

Generates a small PDF receipt for one extraction run, with a basic info
table: filename, inspector, number of findings, extraction time.

The PDF is saved into ./extraction_records/ (created if missing).

USAGE (as a library):
    from extract_case_summary import extract
    from extraction_report import write_extraction_report

    import time
    t0 = time.perf_counter()
    extracted = extract(pdf_path)
    elapsed = time.perf_counter() - t0

    write_extraction_report(extracted, source_pdf=pdf_path, elapsed_seconds=elapsed)

USAGE (as a CLI):
    python extraction_report.py <path-to-pdf>

DEPENDENCIES: reportlab.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if TYPE_CHECKING:
    from extractors.inspection import ExtractedCaseSummary


DEFAULT_OUTPUT_DIR = Path("extraction_records")


def _safe_filename(text: str) -> str:
    """Sanitize a string so it's safe to use as a filename component."""
    text = re.sub(r"[^\w.\-]+", "_", text).strip("_")
    return text or "extraction"


def _count_findings(extracted: "ExtractedCaseSummary") -> int:
    return sum(len(a.findings) for a in extracted.assessments)


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}m {secs:.1f}s"


def write_extraction_report(
    extracted: "ExtractedCaseSummary",
    source_pdf: Path | str | None = None,
    elapsed_seconds: float | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Write a PDF report for one extraction run.

    Returns the path to the generated PDF.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_name = (
        Path(source_pdf).name
        if source_pdf
        else extracted.source_document.file_name
    )
    inspector = extracted.case.consultant.name or "(unassigned)"
    findings_count = _count_findings(extracted)
    extraction_time = _format_elapsed(elapsed_seconds)
    case_number = extracted.case.case_number or "unknown"
    timestamp = datetime.now()

    out_name = (
        f"{_safe_filename(case_number)}"
        f"_{timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    out_path = output_dir / out_name

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Extraction Record {case_number}",
    )

    story = [
        Paragraph("Extraction Record", styles["Title"]),
        Paragraph(
            f"Generated {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"],
        ),
        Spacer(1, 0.25 * inch),
    ]

    table_data = [
        ["Field", "Value"],
        ["Filename", file_name],
        ["Inspector", inspector],
        ["Number of findings", str(findings_count)],
        ["Extraction time", extraction_time],
    ]

    table = Table(table_data, colWidths=[2.0 * inch, 4.5 * inch])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4A7B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.whitesmoke, colors.white]),
        ])
    )
    story.append(table)

    doc.build(story)
    return out_path


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Run extraction and write a PDF extraction record.",
    )
    parser.add_argument("pdf", type=Path, help="Path to PDF file to extract")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder for extraction records (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        sys.exit(1)

    # Imported here so this module can also be imported without triggering
    # the (heavier) extractor import chain.
    from extractors.inspection import extract

    t0 = time.perf_counter()
    extracted = extract(args.pdf)
    elapsed = time.perf_counter() - t0

    out_path = write_extraction_report(
        extracted,
        source_pdf=args.pdf,
        elapsed_seconds=elapsed,
        output_dir=args.output_dir,
    )
    print(f"Wrote extraction record: {out_path}")


if __name__ == "__main__":
    _cli()
