"""
ACP Case Summary PDF Extractor
================================

Extracts structured data from Alberta College of Pharmacy case summary PDFs
into a canonical JSON format suitable for loading into the inspection database.

USAGE:
    python extract_case_summary.py <path-to-pdf> [--output <path-to-json>] [--pretty]

DESIGN NOTES:
- Uses pdfplumber's word-level positional data (x/y coordinates) rather than
  line-based text extraction. This is the only reliable way to handle multi-line
  column values, which appear frequently in category columns.
- Column x-coordinates are hardcoded constants derived from inspecting actual
  ACP case summary PDFs. They have been verified consistent across 3 sample
  documents. If ACP changes their template, update COLUMNS.
- Missing header fields (pharmacy name, licensee, consultant) are tolerated.
  Downstream workflow fills them in via supervisor assignment.
- Verbatim text is preserved exactly. Any summarization is a separate phase.
- Findings are extracted document-wide (not page-by-page) so descriptions
  that span page boundaries are captured intact.

DEPENDENCIES: pdfplumber (only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pdfplumber

if TYPE_CHECKING:
    from pdfplumber.pdf import PDF as PdfPlumberPDF

# =========================================================================
# CONSTANTS
# =========================================================================

EXTRACTOR_VERSION = "0.1.0"

# Column x-coordinate ranges on finding header rows.
# Values derived from inspection of real ACP PDFs; verified consistent.
# A word belongs to a column if its x0 falls within the range.
COLUMNS = {
    "date":               (40,  108),
    "state":              (108, 170),
    "category":           (170, 295),
    "due_date":           (295, 358),
    "person_responsible": (358, 485),
    "completed_date":     (485, 600),
}

# Words that, when found together on the same line, identify a finding
# header row ("Date State Category Due Date Person Responsible Completed Date").
HEADER_MARKERS = {"Date", "State", "Category"}

# Patterns for parsing the case metadata block at the top of page 1.
# Each labeled field is on its own line in the source.
CASE_META_PATTERNS = {
    "pharmacy_name":     re.compile(r"Pharmacy Name:\s*(.+?)\s*$", re.MULTILINE),
    "license_number":    re.compile(r"Pharmacy License:\s*(\S+)"),
    "licensee":          re.compile(r"Pharmacy Licensee:\s*([^(]+?)\s*\(([^)]+)\)"),
    "consultant":        re.compile(r"Pharmacy Practice Consultant:\s*([^(]+?)\s*\(([^)]+)\)"),
    "case_number":       re.compile(r"Case\s*#:\s*(\S+)"),
    "case_type":         re.compile(r"Case Type:\s*(\S+(?:\s\S+)?)\s+Case State:"),
    "case_state":        re.compile(r"Case State:\s*(.+?)\s+Case Closed Date:"),
    "case_closed_date":  re.compile(r"Case Closed Date:\s*(\S.*?)(?:\s*$)", re.MULTILINE),
    "report_generated":  re.compile(r"Report created on:\s*(\S+\s+\S+)"),
}

# Case number appears in the page-1 top strip and/or footer for some
# templates that omit the metadata block (e.g., the SCL example PDF).
# Format: "Page 1 of 14 Case Summary # PP0001972 - Sterile compounding"
FALLBACK_CASE_PATTERN = re.compile(
    r"Case Summary #\s*(\S+)\s*-\s*(.+?)(?:\s+Report created on|\s*$)"
)

# URL extraction — permissive but bounded.
URL_PATTERN = re.compile(r'https?://[^\s\)\]<>"]+[^\s\)\]<>".,;]')

# Regulatory standard references (e.g., "Standard 6.5 of the SOLP", "NAPRA 5.1.2.2")
STANDARD_PATTERNS = [
    re.compile(r"Standard\s+([\d.]+(?:\([a-z0-9]\))?)\s+of\s+the\s+(\w+)", re.IGNORECASE),
    re.compile(r"NAPRA\s+([\d.]+)"),
    re.compile(r"Section\s+([\d.]+)\s+of\s+the\s+([\w\s]+?)(?:[,.\s]|$)"),
]


# =========================================================================
# DATA CLASSES — the canonical extraction schema
# =========================================================================

@dataclass
class Person:
    name: str | None = None
    email: str | None = None


@dataclass
class Consultant(Person):
    role: str | None = None


@dataclass
class Category:
    raw: str
    parent: str | None = None
    child: str | None = None


@dataclass
class StandardReference:
    raw_text: str
    standard_code: str | None = None
    document: str | None = None


@dataclass
class Finding:
    ordinal: int
    identified_date: str | None
    due_date: str | None
    completed_date: str | None
    state: str | None
    person_responsible: str | None
    category: Category | None
    description_verbatim: str
    description_summary: str | None = None
    summary_bullets: list[str] | None = None
    referenced_standards: list[StandardReference] = field(default_factory=list)
    referenced_urls: list[str] = field(default_factory=list)
    source_page_numbers: list[int] = field(default_factory=list)


@dataclass
class Assessment:
    ordinal: int
    assessment_date: str | None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class Case:
    case_number: str | None
    case_type: str | None
    case_state: str | None
    case_closed_date: str | None
    licensee: Person
    consultant: Consultant
    consultant_assignment_status: str  # "confirmed" | "unknown"


@dataclass
class Pharmacy:
    name: str | None
    license_number: str | None


@dataclass
class RegulatoryBody:
    name: str = "Alberta College of Pharmacy"
    short_name: str = "ACP"


@dataclass
class SourceDocument:
    file_hash: str
    file_name: str
    file_size_bytes: int
    mime_type: str = "application/pdf"
    page_count: int = 0
    report_generated_at: str | None = None


@dataclass
class ExtractionMetadata:
    extractor_version: str
    extracted_at: str
    extraction_method: str
    validation_status: str       # "passed" | "passed_with_warnings" | "failed"
    validation_warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class ExtractedCaseSummary:
    extraction_metadata: ExtractionMetadata
    source_document: SourceDocument
    regulatory_body: RegulatoryBody
    pharmacy: Pharmacy
    case: Case
    assessments: list[Assessment]


# =========================================================================
# UTILITIES
# =========================================================================

log = logging.getLogger("extractor")


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file's contents, streamed."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def parse_date(text: str | None) -> str | None:
    """Parse a date string like 'March 19, 2025' into ISO 'YYYY-MM-DD'.

    Returns None if parsing fails or input is empty. Tolerates trailing
    garbage: 'March 28, 2025 ANAPHYLAXIS' parses as 2025-03-28. This is
    important because description headings sometimes bleed into the date
    column on the first line of a finding.
    """
    if not text:
        return None
    text = text.strip().rstrip(",")
    text = re.sub(r"\s+", " ", text)

    # Try exact match first
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    # Fall back: match a date prefix and ignore trailing text.
    prefix_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if prefix_match:
        month, day, year = prefix_match.groups()
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(f"{month} {day} {year}", fmt).date().isoformat()
            except ValueError:
                continue

    log.debug("Could not parse date: %r", text)
    return None


def parse_datetime(text: str | None) -> str | None:
    """Parse a datetime like '06/18/2025 17:57:00' into ISO format."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def split_category(raw: str) -> Category:
    """Split 'Operations : Injections' into parent and child.

    Splits on first ' : ' (space-colon-space). This matters because some
    categories contain hyphens or other colons (e.g., 'Sterile - Personnel :
    Training & Assessment'). Splitting on bare ':' would mangle these.
    """
    raw = raw.strip()
    parts = raw.split(" : ", 1)
    if len(parts) == 2:
        return Category(raw=raw, parent=parts[0].strip(), child=parts[1].strip())
    return Category(raw=raw, parent=None, child=None)


def extract_urls(text: str) -> list[str]:
    """Extract all http(s) URLs from text, preserving order, de-duplicated."""
    seen = set()
    out = []
    for m in URL_PATTERN.finditer(text):
        url = m.group(0)
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_standard_references(text: str) -> list[StandardReference]:
    """Extract references like 'Standard 6.5 of the SOLP' or 'NAPRA 5.1.2.2'."""
    refs: list[StandardReference] = []
    seen = set()

    for pattern in STANDARD_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            if raw in seen:
                continue
            seen.add(raw)
            if "NAPRA" in raw.upper():
                refs.append(StandardReference(
                    raw_text=raw,
                    standard_code=m.group(1),
                    document="NAPRA",
                ))
            else:
                refs.append(StandardReference(
                    raw_text=raw,
                    standard_code=m.group(1) if m.groups() else None,
                    document=m.group(2).strip() if len(m.groups()) >= 2 else None,
                ))
    return refs


# =========================================================================
# COLUMNAR PARSING — the core PDF extraction logic
# =========================================================================

def _classify_column(x0: float) -> str | None:
    """Which column does this x-coordinate fall into? None if outside all."""
    for col_name, (x_min, x_max) in COLUMNS.items():
        if x_min <= x0 < x_max:
            return col_name
    return None


def _line_is_description(line_words: list[dict]) -> bool:
    """Decide if a line is part of the finding description (paragraph) rather
    than a column row OR a column wrap-line continuation.

    Three line types we need to distinguish:
    1. Column row: "March 19, Closed Virtual Care : Virtual April 19, ..."
       — words spread across 6 columns with very large gaps (50+ pt).
    2. Column wrap continuation: "Calibrating, & Maintanence" or
       "2024 Training & Assessment 2024" — words in column areas with
       at least one large gap (the inter-column gap).
    3. Description prose: continuous text where adjacent words are
       separated by normal word-spacing (typically 3-15pt).

    The discriminating signal is the LARGEST gap between consecutive words.
    Prose has max-gap < 20pt (just word spacing). Column rows and wrap
    rows always have at least one gap ≥ 20pt (the inter-column whitespace).
    """
    if not line_words:
        return False

    sorted_words = sorted(line_words, key=lambda w: w["x0"])

    if len(sorted_words) < 2:
        # Single word: a date wrap "2025" or a one-word heading.
        # Treat as not-description (column wrap).
        return False

    max_gap = 0.0
    for prev, curr in zip(sorted_words, sorted_words[1:]):
        gap = curr["x0"] - prev["x1"]
        if gap > max_gap:
            max_gap = gap

    if max_gap < 20:
        # Looks like prose. Guard against very short lines that might
        # just be a column wrap with tight spacing.
        return len(sorted_words) >= 4

    return False


def _is_decoration_word(w: dict) -> bool:
    """Identify words that are page decoration (headers, footers).

    Page header strip: very top (y < 35) — "Page N of M Case Summary #..."
    Page footer strip: bottom ~60pt — "Report created on: ..."
    """
    page_height = w["page_height"]
    y = w["top"]
    if y < 35:
        return True
    if y > page_height - 60:
        return True
    return False


def collect_all_words(pdf: PdfPlumberPDF) -> list[dict]:
    """Collect every word from every page, annotated with page number and
    a global y-coordinate.

    The global y is `page_index * 10000 + page_y`, which preserves order
    across pages without overlap (page heights are <800 in points).

    Returns a list sorted by global_y.
    """
    out: list[dict] = []
    for page_idx, page in enumerate(pdf.pages):
        for w in page.extract_words():
            out.append({
                **w,
                "page_number": page_idx + 1,
                "global_y": page_idx * 10000 + w["top"],
                "page_height": page.height,
                "page_index": page_idx,
            })
    out.sort(key=lambda w: w["global_y"])
    return out


def find_header_rows_global(all_words: list[dict]) -> list[dict]:
    """Find every finding-block header row across the whole document.

    Returns a list of dicts: {global_y, page_number, page_y, page_index}.
    """
    lines: dict[tuple[int, float], list[dict]] = {}
    for w in all_words:
        key = (w["page_index"], round(w["top"] / 2) * 2)
        lines.setdefault(key, []).append(w)

    header_rows = []
    for (page_idx, page_y), words in lines.items():
        texts = {w["text"] for w in words}
        if HEADER_MARKERS.issubset(texts):
            header_rows.append({
                "global_y": page_idx * 10000 + page_y,
                "page_number": page_idx + 1,
                "page_y": page_y,
                "page_index": page_idx,
            })
    header_rows.sort(key=lambda h: h["global_y"])
    return header_rows


def _extract_finding_block(
    all_words: list[dict],
    header_global_y: float,
    next_header_global_y: float,
    header_page_index: int,
) -> dict:
    """Extract one finding block: column values and description text.

    Operates over global y-coordinates so descriptions can span page
    boundaries. Skips footer/header decoration words.
    """
    # All words in this finding's vertical band
    band_words = [
        w for w in all_words
        if header_global_y + 6 < w["global_y"] < next_header_global_y
    ]
    band_words = [w for w in band_words if not _is_decoration_word(w)]

    # Group into "global lines" — same page AND similar y
    lines: dict[tuple[int, float], list[dict]] = {}
    for w in band_words:
        key = (w["page_index"], round(w["top"] / 2) * 2)
        lines.setdefault(key, []).append(w)
    sorted_keys = sorted(lines.keys())

    column_values: dict[str, list[str]] = {k: [] for k in COLUMNS}
    description_lines: list[str] = []
    page_numbers: list[int] = []

    description_started = False
    for key in sorted_keys:
        line_words = sorted(lines[key], key=lambda w: w["x0"])
        if not line_words:
            continue

        if not description_started:
            if _line_is_description(line_words):
                description_started = True
                description_lines.append(" ".join(w["text"] for w in line_words))
                if line_words[0]["page_number"] not in page_numbers:
                    page_numbers.append(line_words[0]["page_number"])
            else:
                # Column-zone line — assign words to columns
                for w in line_words:
                    col = _classify_column(w["x0"])
                    if col:
                        column_values[col].append(w["text"])
        else:
            # Already in description; everything after is description text
            description_lines.append(" ".join(w["text"] for w in line_words))
            if line_words[0]["page_number"] not in page_numbers:
                page_numbers.append(line_words[0]["page_number"])

    description = re.sub(r"\s+", " ", " ".join(description_lines)).strip()
    joined_columns = {k: " ".join(v).strip() for k, v in column_values.items()}

    if not page_numbers:
        page_numbers = [header_page_index + 1]

    return {
        **joined_columns,
        "description": description,
        "page_numbers": page_numbers,
    }


def extract_findings_global(pdf: PdfPlumberPDF) -> list[dict]:
    """Extract all findings document-wide, allowing descriptions to span pages.

    Returns a list of raw finding dicts with keys:
        date, state, category, due_date, person_responsible, completed_date,
        description, page_numbers (list).
    """
    all_words = collect_all_words(pdf)
    headers = find_header_rows_global(all_words)

    findings = []
    for i, h in enumerate(headers):
        next_h = headers[i + 1]["global_y"] if i + 1 < len(headers) else float("inf")
        findings.append(_extract_finding_block(
            all_words=all_words,
            header_global_y=h["global_y"],
            next_header_global_y=next_h,
            header_page_index=h["page_index"],
        ))
    return findings


# =========================================================================
# CASE METADATA EXTRACTION
# =========================================================================

def extract_case_metadata(pdf: PdfPlumberPDF) -> dict[str, Any]:
    """Extract case metadata (pharmacy, licensee, consultant, case #, etc.)
    from page 1.

    Tolerates missing fields: if the labeled metadata block is absent,
    returns None for those fields. Case number is recovered from the page
    header strip and footer as fallbacks.
    """
    if len(pdf.pages) == 0:
        return {}

    page1 = pdf.pages[0]

    # The labeled metadata block is in the upper half of page 1
    top_text = page1.crop(
        (0, 0, page1.width, page1.height * 0.55)
    ).extract_text() or ""

    result: dict[str, Any] = {
        "pharmacy_name": None,
        "license_number": None,
        "licensee_name": None,
        "licensee_email": None,
        "consultant_name": None,
        "consultant_email": None,
        "case_number": None,
        "case_type": None,
        "case_state": None,
        "case_closed_date": None,
        "report_generated_at": None,
    }

    if (m := CASE_META_PATTERNS["pharmacy_name"].search(top_text)):
        result["pharmacy_name"] = m.group(1).strip()
    if (m := CASE_META_PATTERNS["license_number"].search(top_text)):
        result["license_number"] = m.group(1).strip()
    if (m := CASE_META_PATTERNS["licensee"].search(top_text)):
        result["licensee_name"] = m.group(1).strip()
        result["licensee_email"] = m.group(2).strip()
    if (m := CASE_META_PATTERNS["consultant"].search(top_text)):
        result["consultant_name"] = m.group(1).strip()
        result["consultant_email"] = m.group(2).strip()
    if (m := CASE_META_PATTERNS["case_number"].search(top_text)):
        result["case_number"] = m.group(1).strip()
    if (m := CASE_META_PATTERNS["case_type"].search(top_text)):
        result["case_type"] = m.group(1).strip()
    if (m := CASE_META_PATTERNS["case_state"].search(top_text)):
        result["case_state"] = m.group(1).strip()
    if (m := CASE_META_PATTERNS["case_closed_date"].search(top_text)):
        if m.group(1).strip():
            result["case_closed_date"] = parse_date(m.group(1))

    # Report generation timestamp from page footer
    footer_text = page1.crop(
        (0, page1.height * 0.94, page1.width, page1.height)
    ).extract_text() or ""
    if (m := CASE_META_PATTERNS["report_generated"].search(footer_text)):
        result["report_generated_at"] = parse_datetime(m.group(1))

    # Fallback: case_number from the page-1 header strip or footer.
    # Some PDFs omit the metadata block entirely but always have the
    # "Page N of M Case Summary # XXX - Type" line.
    if not result["case_number"]:
        header_strip = page1.crop(
            (0, 0, page1.width, page1.height * 0.05)
        ).extract_text() or ""
        for source in (header_strip, footer_text):
            if (m := FALLBACK_CASE_PATTERN.search(source)):
                result["case_number"] = m.group(1).strip()
                if not result["case_type"]:
                    result["case_type"] = m.group(2).strip()
                break

    return result


# =========================================================================
# ASSEMBLY — turn raw extraction into the canonical schema
# =========================================================================

def group_findings_into_assessments(
    raw_findings: list[dict],
) -> list[Assessment]:
    """Group findings by their identified_date into Assessment objects.

    Findings sharing the same date belong to the same assessment (visit).
    Assessments are ordered chronologically; findings with unparseable
    dates land in a final "unknown" assessment for human review.
    """
    by_date: dict[str, list[dict]] = {}
    seen_dates: list[str] = []
    for f in raw_findings:
        iso_date = parse_date(f.get("date"))
        key = iso_date or "__unknown__"
        if key not in by_date:
            seen_dates.append(key)
            by_date[key] = []
        by_date[key].append(f)

    # Sort: known dates chronologically, unknown last
    known = sorted([d for d in seen_dates if d != "__unknown__"])
    if "__unknown__" in seen_dates:
        known.append("__unknown__")

    assessments = []
    for ordinal, date_key in enumerate(known, start=1):
        raw_list = by_date[date_key]
        findings = []
        for f_ord, f in enumerate(raw_list, start=1):
            description = f.get("description", "")
            category_raw = f.get("category", "").strip()
            findings.append(Finding(
                ordinal=f_ord,
                identified_date=parse_date(f.get("date")),
                due_date=parse_date(f.get("due_date")),
                completed_date=parse_date(f.get("completed_date")),
                state=f.get("state") or None,
                person_responsible=f.get("person_responsible") or None,
                category=split_category(category_raw) if category_raw else None,
                description_verbatim=description,
                referenced_urls=extract_urls(description),
                referenced_standards=extract_standard_references(description),
                source_page_numbers=f.get("page_numbers", []),
            ))
        assessments.append(Assessment(
            ordinal=ordinal,
            assessment_date=date_key if date_key != "__unknown__" else None,
            findings=findings,
        ))
    return assessments


# =========================================================================
# VALIDATION
# =========================================================================

def validate(extracted: ExtractedCaseSummary) -> tuple[str, list[str], list[str]]:
    """Validate extraction output.

    Returns (status, warnings, errors):
    - errors (blocking) → status = 'failed'
    - warnings only → status = 'passed_with_warnings'
    - clean → status = 'passed'
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Hard requirements
    if not extracted.case.case_number:
        errors.append("case_number is missing (not found in header or footer)")

    total_findings = sum(len(a.findings) for a in extracted.assessments)
    if total_findings == 0:
        errors.append("no findings were extracted from the document")

    # Soft warnings — missing identifying metadata
    if not extracted.pharmacy.name:
        warnings.append("pharmacy name missing — will require supervisor assignment")
    if not extracted.pharmacy.license_number:
        warnings.append("pharmacy license number missing")
    if not extracted.case.licensee.name:
        warnings.append("licensee name missing")
    if not extracted.case.consultant.name:
        warnings.append("consultant name missing — will require supervisor assignment")

    # Findings-level checks
    for a in extracted.assessments:
        for f in a.findings:
            label = f"assessment {a.ordinal}, finding {f.ordinal}"
            if not f.identified_date:
                warnings.append(f"{label}: identified_date could not be parsed")
            if not f.description_verbatim or len(f.description_verbatim) < 20:
                warnings.append(f"{label}: description unusually short or empty")
            if f.category is None:
                warnings.append(f"{label}: category missing")

    if errors:
        return "failed", warnings, errors
    if warnings:
        return "passed_with_warnings", warnings, errors
    return "passed", warnings, errors


# =========================================================================
# TOP-LEVEL ENTRY POINT
# =========================================================================

def extract(pdf_path: Path) -> ExtractedCaseSummary:
    """Main entry point: parse a PDF into an ExtractedCaseSummary."""
    log.info("Opening %s", pdf_path)

    file_hash = sha256_file(pdf_path)
    file_size = pdf_path.stat().st_size

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        log.info("Document has %d pages", page_count)

        meta = extract_case_metadata(pdf)
        log.info(
            "Case metadata: case=%s, pharmacy=%s, consultant=%s",
            meta.get("case_number"),
            meta.get("pharmacy_name"),
            meta.get("consultant_name"),
        )

        raw_findings = extract_findings_global(pdf)
        log.info("Extracted %d raw finding blocks", len(raw_findings))

        assessments = group_findings_into_assessments(raw_findings)
        log.info("Grouped into %d assessments", len(assessments))

    consultant = Consultant(
        name=meta.get("consultant_name"),
        email=meta.get("consultant_email"),
        role="Pharmacy Practice Consultant" if meta.get("consultant_name") else None,
    )
    consultant_status = "confirmed" if consultant.name else "unknown"

    extracted = ExtractedCaseSummary(
        extraction_metadata=ExtractionMetadata(
            extractor_version=EXTRACTOR_VERSION,
            extracted_at=datetime.now(timezone.utc).isoformat(),
            extraction_method="pdfplumber_columnar",
            validation_status="pending",
        ),
        source_document=SourceDocument(
            file_hash=file_hash,
            file_name=pdf_path.name,
            file_size_bytes=file_size,
            page_count=page_count,
            report_generated_at=meta.get("report_generated_at"),
        ),
        regulatory_body=RegulatoryBody(),
        pharmacy=Pharmacy(
            name=meta.get("pharmacy_name"),
            license_number=meta.get("license_number"),
        ),
        case=Case(
            case_number=meta.get("case_number"),
            case_type=meta.get("case_type"),
            case_state=meta.get("case_state"),
            case_closed_date=meta.get("case_closed_date"),
            licensee=Person(
                name=meta.get("licensee_name"),
                email=meta.get("licensee_email"),
            ),
            consultant=consultant,
            consultant_assignment_status=consultant_status,
        ),
        assessments=assessments,
    )

    status, warnings, errors = validate(extracted)
    extracted.extraction_metadata.validation_status = status
    extracted.extraction_metadata.validation_warnings = warnings
    extracted.extraction_metadata.validation_errors = errors

    log.info("Validation: %s (%d warnings, %d errors)",
             status, len(warnings), len(errors))

    return extracted


def to_json_dict(extracted: ExtractedCaseSummary) -> dict[str, Any]:
    """Convert the extraction to a plain dict (recursively handles dataclasses)."""
    return asdict(extracted)


# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract ACP case summary PDF to canonical JSON",
    )
    parser.add_argument("pdf", type=Path, help="Path to PDF file")
    parser.add_argument("--output", type=Path, help="Output JSON path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Also write a PDF extraction record into ./extraction_records/",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.pdf.exists():
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        sys.exit(1)

    t0 = time.perf_counter()
    extracted = extract(args.pdf)
    elapsed = time.perf_counter() - t0
    result = to_json_dict(extracted)

    text = json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(text)

    if args.record:
        from generate_extraction_pdfs import write_extraction_report
        record_path = write_extraction_report(
            extracted, source_pdf=args.pdf, elapsed_seconds=elapsed,
        )
        print(f"Wrote extraction record: {record_path}", file=sys.stderr)

    sys.exit(0 if extracted.extraction_metadata.validation_status != "failed" else 2)


if __name__ == "__main__":
    main()
