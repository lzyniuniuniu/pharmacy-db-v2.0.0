"""Top-level extractor CLI: classifies a PDF and dispatches to the
appropriate extractor.

Usage:
    python extract.py <path-to-pdf> [--output <path-to-json>] [--pretty]
                                    [--force-type <document_type>]
                                    [--verbose]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pdfplumber

from extractors.base import Extractor
from extractors.registry import get_extractors

log = logging.getLogger("dispatcher")


class NoMatchingExtractor(Exception):
    """Raised when no registered extractor recognizes the document."""


class AmbiguousMatch(Exception):
    """Raised when multiple extractors claim to handle the document.

    This is a configuration bug — extractors should be specific enough
    that only one matches a given file. If this fires, fix the can_handle
    logic of the offending extractors.
    """


def select_extractor(pdf_path: Path, force_type: str | None = None) -> Extractor:
    """Pick the right extractor for a PDF.

    Opens the PDF once, asks each registered extractor whether it can
    handle the document, returns the unique match.

    If `force_type` is provided, skips detection and returns the
    extractor whose DOCUMENT_TYPE matches.
    """
    extractors = get_extractors()

    if force_type is not None:
        for ex in extractors:
            if ex.DOCUMENT_TYPE == force_type:
                log.info("Forced extractor: %s", type(ex).__name__)
                return ex
        raise NoMatchingExtractor(
            f"No extractor registered for document type {force_type!r}. "
            f"Available: {[e.DOCUMENT_TYPE for e in extractors]}"
        )

    matches: list[Extractor] = []
    with pdfplumber.open(pdf_path) as pdf:
        for ex in extractors:
            if ex.can_handle(pdf):
                matches.append(ex)
                log.debug("%s: matched", type(ex).__name__)
            else:
                log.debug("%s: no match", type(ex).__name__)

    if not matches:
        raise NoMatchingExtractor(
            f"No registered extractor recognizes {pdf_path.name}. "
            f"Tried: {[type(e).__name__ for e in extractors]}"
        )
    if len(matches) > 1:
        raise AmbiguousMatch(
            f"Multiple extractors matched {pdf_path.name}: "
            f"{[type(e).__name__ for e in matches]}. "
            "Tighten can_handle logic to disambiguate."
        )

    log.info("Selected extractor: %s (type=%s)",
             type(matches[0]).__name__, matches[0].DOCUMENT_TYPE)
    return matches[0]


def extract(pdf_path: Path, force_type: str | None = None) -> dict[str, Any]:
    """Extract a PDF, dispatching to the appropriate extractor.

    Returns the canonical JSON dict.
    """
    extractor = select_extractor(pdf_path, force_type=force_type)
    return extractor.extract(pdf_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract structured data from a regulatory PDF document",
    )
    parser.add_argument("pdf", type=Path, help="Path to PDF file")
    parser.add_argument("--output", type=Path, help="Output JSON path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--force-type",
        help="Skip detection and force a specific document type "
             "(e.g., 'case_summary'). Useful for testing.",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.pdf.exists():
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        sys.exit(1)

    try:
        result = extract(args.pdf, force_type=args.force_type)
    except NoMatchingExtractor as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except AmbiguousMatch as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)

    text = json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(text)

    # Exit code reflects validation status of the extraction
    status = result.get("extraction_metadata", {}).get("validation_status", "passed")
    sys.exit(0 if status != "failed" else 4)


if __name__ == "__main__":
    main()