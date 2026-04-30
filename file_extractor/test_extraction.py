import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from extractors.inspection import extract


DEFAULT_FOLDER = Path(
    "/Users/marklu/Desktop/Algo-Pharm_formal/raw_data/Mint_Action_Reports"
)

parser = argparse.ArgumentParser(
    description="Batch-extract every PDF in a folder and write a summary report.",
)
parser.add_argument(
    "folder",
    nargs="?",
    type=Path,
    default=DEFAULT_FOLDER,
    help=f"Folder containing PDFs to extract (default: {DEFAULT_FOLDER})",
)
args = parser.parse_args()

folder: Path = args.folder
if not folder.is_dir():
    print(f"Error: folder not found: {folder}", file=sys.stderr)
    sys.exit(1)

pdfs = sorted(folder.glob("*.pdf"))
if not pdfs:
    print(f"Error: no PDFs found in {folder}", file=sys.stderr)
    sys.exit(1)

records_dir = Path("extraction_records")
records_dir.mkdir(parents=True, exist_ok=True)

results = []
summary_rows = []
total_elapsed = 0.0
total_findings = 0
status_counts: dict[str, int] = {}
failures: list[tuple[str, str]] = []

batch_t0 = time.perf_counter()
for pdf in pdfs:
    try:
        t0 = time.perf_counter()
        res = extract(pdf)
        elapsed = time.perf_counter() - t0
    except Exception as e:
        failures.append((pdf.name, f"{type(e).__name__}: {e}"))
        continue

    results.append(asdict(res))
    findings_n = sum(len(a.findings) for a in res.assessments)
    status = res.extraction_metadata.validation_status
    inspector = res.case.consultant.name or "(unassigned)"
    total_elapsed += elapsed
    total_findings += findings_n
    status_counts[status] = status_counts.get(status, 0) + 1
    summary_rows.append({
        "file": pdf.name,
        "case": res.case.case_number or "-",
        "inspector": inspector,
        "findings": findings_n,
        "status": status,
        "elapsed": elapsed,
    })

batch_elapsed = time.perf_counter() - batch_t0
Path("combined.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))

# ---- Write a single batch summary PDF ----
timestamp = datetime.now()
out_pdf = records_dir / f"batch_summary_{timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"

styles = getSampleStyleSheet()
doc = SimpleDocTemplate(
    str(out_pdf),
    pagesize=landscape(LETTER),
    leftMargin=0.5 * inch, rightMargin=0.5 * inch,
    topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    title="Batch Extraction Summary",
)

story = [
    Paragraph("Batch Extraction Summary", styles["Title"]),
    Paragraph(f"Generated {timestamp.strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]),
    Paragraph(f"Source folder: {folder}", styles["Normal"]),
    Spacer(1, 0.2 * inch),
]

totals_data = [
    ["Metric", "Value"],
    ["PDFs processed", str(len(summary_rows))],
    ["PDFs failed", str(len(failures))],
    ["Total findings", str(total_findings)],
    ["Status breakdown",
     ", ".join(f"{k}: {v}" for k, v in status_counts.items()) or "-"],
    ["Sum of extract times", f"{total_elapsed:.2f} s"],
    ["Wall clock time", f"{batch_elapsed:.2f} s"],
]
totals = Table(totals_data, colWidths=[2.0 * inch, 6.5 * inch])
totals.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4A7B")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
]))
story += [totals, Spacer(1, 0.3 * inch)]

story.append(Paragraph("Per-file results", styles["Heading2"]))
header: list[str | Paragraph] = ["#", "File", "Case", "Inspector", "Findings", "Status", "Time (s)"]
cell_style = styles["BodyText"]
cell_style.fontSize = 9
cell_style.leading = 11
data: list[list[str | Paragraph]] = [header]
for i, r in enumerate(summary_rows, 1):
    data.append([
        str(i),
        Paragraph(r["file"], cell_style),
        r["case"],
        Paragraph(r["inspector"], cell_style),
        str(r["findings"]),
        Paragraph(r["status"], cell_style),
        f"{r['elapsed']:.2f}",
    ])
per_file = Table(
    data,
    colWidths=[0.35 * inch, 4.0 * inch, 1.0 * inch, 1.5 * inch,
               0.7 * inch, 0.7 * inch, 0.65 * inch],
    repeatRows=1,
)
per_file.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4A7B")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ("ALIGN", (4, 1), (4, -1), "RIGHT"),
    ("ALIGN", (6, 1), (6, -1), "RIGHT"),
]))
story.append(per_file)

if failures:
    story += [Spacer(1, 0.3 * inch), Paragraph("Failures", styles["Heading2"])]
    fail_data = [["File", "Error"]] + [[n, e] for n, e in failures]
    ftable = Table(fail_data, colWidths=[2.6 * inch, 6.0 * inch], repeatRows=1)
    ftable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8B2E2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ftable)

doc.build(story)

print(f"Extracted {len(summary_rows)} files ({len(failures)} failed)")
print(f"Combined JSON:  combined.json")
print(f"Summary PDF:    {out_pdf}")
