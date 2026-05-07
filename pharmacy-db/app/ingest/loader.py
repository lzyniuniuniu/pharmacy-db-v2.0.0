"""Loader: reads an extractor JSON file and populates the database.

The loader is idempotent. Running it twice on the same JSON results in
the same database state. Mutable fields are updated to match the latest
extraction; identity fields are stable.

Usage as a module:
    docker compose exec app python -m app.ingest.loader path/to/extraction.json

Usage from Python:
    from app.ingest.loader import load_extraction
    case = load_extraction(json_path, db_session)
    db_session.commit()
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.case import Case
from app.services.assessments import get_or_create_assessment
from app.services.cases import get_or_create_case
from app.services.documents import get_or_create_document
from app.services.finding_categories import get_or_create_category
from app.services.findings import get_or_create_finding
from app.services.inspectors import get_or_create_inspector
from app.services.pharmacies import get_or_create_pharmacy
from app.services.regulatory_bodies import get_or_create_regulatory_body

log = logging.getLogger("loader")


# -------------------------------------------------------------------------
# Helpers — date parsing from JSON strings
# -------------------------------------------------------------------------


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


# -------------------------------------------------------------------------
# Main entry points
# -------------------------------------------------------------------------


def load_extraction_dict(data: dict[str, Any], db: Session) -> Case:
    """Load one extraction (already parsed as a dict) into the database.

    Returns the Case row. Does NOT commit — caller controls the transaction.
    """
    # Refuse to load extractions that failed validation
    validation_status = data["extraction_metadata"]["validation_status"]
    if validation_status == "failed":
        errors = data["extraction_metadata"].get("validation_errors", [])
        raise ValueError(f"Extraction failed validation: {errors}")

    # Step 1: regulatory body
    body_data = data["regulatory_body"]
    body = get_or_create_regulatory_body(
        db,
        name=body_data["name"],
        short_name=body_data["short_name"],
    )
    log.info("regulatory_body: %s (id=%s)", body.short_name, body.id)

    # Step 2: pharmacy (may be None if both fields missing)
    pharmacy_data = data["pharmacy"]
    pharmacy = get_or_create_pharmacy(
        db,
        regulatory_body_id=body.id,
        license_number=pharmacy_data["license_number"],
        name=pharmacy_data["name"],
    )
    if pharmacy is not None:
        log.info("pharmacy: %s (id=%s)", pharmacy.name or pharmacy.license_number, pharmacy.id)
    else:
        log.info("pharmacy: none (will require supervisor assignment)")

    # Step 3: consultant (may be None if no consultant info in extraction)
    case_data = data["case"]
    consultant_data = case_data["consultant"]
    consultant = get_or_create_inspector(
        db,
        regulatory_body_id=body.id,
        full_name=consultant_data["name"] if consultant_data else None,
        email=consultant_data["email"] if consultant_data else None,
        role=consultant_data["role"] if consultant_data else None,
    )
    if consultant is not None:
        log.info("consultant: %s (id=%s)", consultant.full_name, consultant.id)
    else:
        log.info("consultant: none (will require supervisor assignment)")

    # Step 4: source document
    source_doc_data = data["source_document"]
    document = get_or_create_document(
        db,
        file_hash=source_doc_data["file_hash"],
        file_name=source_doc_data["file_name"],
        document_type=data.get("document_type", "case_summary"),
        file_size_bytes=source_doc_data.get("file_size_bytes"),
        mime_type=source_doc_data.get("mime_type"),
        page_count=source_doc_data.get("page_count"),
        report_generated_at=_parse_datetime(source_doc_data.get("report_generated_at")),
        extraction_metadata=data["extraction_metadata"],
    )
    log.info("document: %s (id=%s)", document.file_name, document.id)

    # Step 5: case
    case = get_or_create_case(
        db,
        regulatory_body_id=body.id,
        case_number=case_data["case_number"],
        pharmacy_id=pharmacy.id if pharmacy else None,
        consultant_id=consultant.id if consultant else None,
        case_type=case_data.get("case_type"),
        case_state=case_data.get("case_state"),
        case_closed_date=_parse_date(case_data.get("case_closed_date")),
        licensee_name=case_data["licensee"]["name"] if case_data.get("licensee") else None,
        licensee_email=case_data["licensee"]["email"] if case_data.get("licensee") else None,
        consultant_assignment_status=case_data.get("consultant_assignment_status", "unknown"),
    )
    log.info("case: %s (id=%s)", case.case_number, case.id)

    # Step 5b: link the document back to the case
    document.case_id = case.id

    # Step 6: assessments and their findings
    for assessment_data in data["assessments"]:
        assessment = get_or_create_assessment(
            db,
            case_id=case.id,
            ordinal=assessment_data["ordinal"],
            assessment_date=_parse_date(assessment_data.get("assessment_date")),
        )
        log.info(
            "  assessment %d: %s (id=%s)",
            assessment.ordinal,
            assessment.assessment_date,
            assessment.id,
        )

        for finding_data in assessment_data["findings"]:
            # Resolve category if present
            category = None
            category_data = finding_data.get("category")
            if category_data is not None:
                category = get_or_create_category(
                    db,
                    regulatory_body_id=body.id,
                    full_path=category_data["raw"],
                )

            get_or_create_finding(
                db,
                assessment_id=assessment.id,
                case_id=case.id,
                ordinal=finding_data["ordinal"],
                description_verbatim=finding_data["description_verbatim"],
                category_id=category.id if category else None,
                source_document_id=document.id,
                identified_date=_parse_date(finding_data.get("identified_date")),
                due_date=_parse_date(finding_data.get("due_date")),
                completed_date=_parse_date(finding_data.get("completed_date")),
                state=finding_data.get("state"),
                person_responsible=finding_data.get("person_responsible"),
                category_raw=category_data["raw"] if category_data else None,
                referenced_standards=finding_data.get("referenced_standards"),
                referenced_urls=finding_data.get("referenced_urls"),
                source_page_numbers=finding_data.get("source_page_numbers"),
            )

        log.info("    %d findings loaded", len(assessment_data["findings"]))

    return case


def load_extraction(json_path: Path, db: Session) -> Case:
    """Load one extractor JSON file into the database.

    Returns the Case row. Does NOT commit.
    """
    log.info("Loading %s", json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return load_extraction_dict(data, db)


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------


def _cli(paths: list[Path]) -> int:
    """Load one or more extraction JSON files."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    failures: list[tuple[Path, str]] = []
    successes = 0

    for path in paths:
        if not path.exists():
            log.error("File not found: %s", path)
            failures.append((path, "file not found"))
            continue

        db = SessionLocal()
        try:
            case = load_extraction(path, db)
            db.commit()
            log.info("✓ Loaded %s as case %s (db id %s)", path.name, case.case_number, case.id)
            successes += 1
        except Exception as e:
            db.rollback()
            log.exception("✗ Failed to load %s", path)
            failures.append((path, str(e)))
        finally:
            db.close()

    log.info("Done: %d succeeded, %d failed", successes, len(failures))
    for path, reason in failures:
        log.error("  failed: %s (%s)", path, reason)

    return 0 if not failures else 2


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.ingest.loader <path-to-json> [more paths...]", file=sys.stderr)
        sys.exit(1)
    paths = [Path(p) for p in sys.argv[1:]]
    sys.exit(_cli(paths))


if __name__ == "__main__":
    main()