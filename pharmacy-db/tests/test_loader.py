import json
from pathlib import Path

import pytest

from app.ingest.loader import load_extraction_dict
from app.models.assessment import Assessment
from app.models.case import Case
from app.models.document import Document
from app.models.finding import Finding
from app.models.finding_category import FindingCategory
from app.models.inspector import Inspector
from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody


# A minimal valid extraction dict. Build on this in each test.
def _minimal_extraction(**overrides) -> dict:
    base = {
        "extraction_metadata": {
            "extractor_version": "0.1.0",
            "extracted_at": "2026-04-25T12:00:00+00:00",
            "extraction_method": "pdfplumber_columnar",
            "validation_status": "passed",
            "validation_warnings": [],
            "validation_errors": [],
        },
        "source_document": {
            "file_hash": "sha256:" + "a" * 64,
            "file_name": "test.pdf",
            "file_size_bytes": 100000,
            "mime_type": "application/pdf",
            "page_count": 11,
            "report_generated_at": "2025-06-18T17:57:00",
        },
        "regulatory_body": {
            "name": "Alberta College of Pharmacy",
            "short_name": "ACP",
        },
        "pharmacy": {
            "name": "Mint Health + Drugs: Beaverlodge",
            "license_number": "3538",
        },
        "case": {
            "case_number": "PP0002449",
            "case_type": "Routine",
            "case_state": "Work in Progress",
            "case_closed_date": None,
            "licensee": {"name": "Rebecca Perrin", "email": "becky.p@mintdrugs.com"},
            "consultant": {
                "name": "Tyler Watson",
                "email": "tyler.watson@abpharmacy.ca",
                "role": "Pharmacy Practice Consultant",
            },
            "consultant_assignment_status": "confirmed",
        },
        "assessments": [
            {
                "ordinal": 1,
                "assessment_date": "2025-03-19",
                "findings": [
                    {
                        "ordinal": 1,
                        "identified_date": "2025-03-19",
                        "due_date": "2025-04-19",
                        "completed_date": "2025-04-08",
                        "state": "Closed",
                        "person_responsible": "Rebecca Perrin",
                        "category": {
                            "raw": "Operations : Injections",
                            "parent": "Operations",
                            "child": "Injections",
                        },
                        "description_verbatim": "Sample finding text.",
                        "description_summary": None,
                        "summary_bullets": None,
                        "referenced_standards": [],
                        "referenced_urls": [],
                        "source_page_numbers": [2],
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def test_loads_full_extraction(db_session):
    data = _minimal_extraction()
    case = load_extraction_dict(data, db_session)
    db_session.flush()

    # All entities created
    assert db_session.query(RegulatoryBody).count() == 1
    assert db_session.query(Pharmacy).count() == 1
    assert db_session.query(Inspector).count() == 1
    assert db_session.query(Document).count() == 1
    assert db_session.query(Case).count() == 1
    assert db_session.query(Assessment).count() == 1
    assert db_session.query(FindingCategory).count() == 1
    assert db_session.query(Finding).count() == 1

    # The case has the expected relationships
    assert case.case_number == "PP0002449"
    assert case.pharmacy is not None
    assert case.pharmacy.name == "Mint Health + Drugs: Beaverlodge"
    assert case.consultant is not None
    assert case.consultant.full_name == "Tyler Watson"

    # Document is linked back to the case
    document = db_session.query(Document).one()
    assert document.case_id == case.id


def test_loader_is_idempotent(db_session):
    """Running the same load twice produces the same state."""
    data = _minimal_extraction()

    load_extraction_dict(data, db_session)
    db_session.flush()

    # Snapshot counts
    counts_before = {
        "regulatory_body": db_session.query(RegulatoryBody).count(),
        "pharmacy": db_session.query(Pharmacy).count(),
        "inspector": db_session.query(Inspector).count(),
        "document": db_session.query(Document).count(),
        "case": db_session.query(Case).count(),
        "assessment": db_session.query(Assessment).count(),
        "category": db_session.query(FindingCategory).count(),
        "finding": db_session.query(Finding).count(),
    }

    load_extraction_dict(data, db_session)
    db_session.flush()

    counts_after = {
        "regulatory_body": db_session.query(RegulatoryBody).count(),
        "pharmacy": db_session.query(Pharmacy).count(),
        "inspector": db_session.query(Inspector).count(),
        "document": db_session.query(Document).count(),
        "case": db_session.query(Case).count(),
        "assessment": db_session.query(Assessment).count(),
        "category": db_session.query(FindingCategory).count(),
        "finding": db_session.query(Finding).count(),
    }

    assert counts_before == counts_after


def test_re_extraction_updates_mutable_fields(db_session):
    """If the same case is re-extracted with a new state, the case is updated."""
    data = _minimal_extraction()
    data["case"]["case_state"] = "Work in Progress"
    load_extraction_dict(data, db_session)
    db_session.flush()

    # New extraction shows the case as Closed now
    data["case"]["case_state"] = "Closed"
    data["case"]["case_closed_date"] = "2025-04-08"
    load_extraction_dict(data, db_session)
    db_session.flush()

    case = db_session.query(Case).one()
    assert case.case_state == "Closed"
    assert case.case_closed_date.isoformat() == "2025-04-08"


def test_re_extraction_preserves_summary_fields(db_session):
    """The LLM might have populated description_summary; re-extracting
    should not blow it away."""
    data = _minimal_extraction()
    load_extraction_dict(data, db_session)
    db_session.flush()

    finding = db_session.query(Finding).one()
    finding.description_summary = "LLM-generated summary."
    finding.summary_bullets = ["Point one", "Point two"]
    db_session.flush()

    # Re-load
    load_extraction_dict(data, db_session)
    db_session.flush()

    finding = db_session.query(Finding).one()
    assert finding.description_summary == "LLM-generated summary."
    assert finding.summary_bullets == ["Point one", "Point two"]


def test_loader_handles_missing_pharmacy(db_session):
    """The SCL workflow: pharmacy info is missing in the source PDF."""
    data = _minimal_extraction(pharmacy={"name": None, "license_number": None})

    case = load_extraction_dict(data, db_session)
    db_session.flush()

    assert case.pharmacy_id is None
    assert db_session.query(Pharmacy).count() == 0


def test_loader_handles_missing_consultant(db_session):
    """The SCL workflow: consultant info is missing in the source PDF."""
    data = _minimal_extraction()
    data["case"]["consultant"] = None
    data["case"]["consultant_assignment_status"] = "unknown"

    case = load_extraction_dict(data, db_session)
    db_session.flush()

    assert case.consultant_id is None
    assert case.consultant_assignment_status == "unknown"
    assert db_session.query(Inspector).count() == 0


def test_loader_refuses_failed_extraction(db_session):
    """Extractions marked as failed should not be loaded."""
    data = _minimal_extraction()
    data["extraction_metadata"]["validation_status"] = "failed"
    data["extraction_metadata"]["validation_errors"] = ["test error"]

    with pytest.raises(ValueError, match="failed validation"):
        load_extraction_dict(data, db_session)


def test_loader_handles_multiple_assessments_with_findings(db_session):
    """A case with multiple visits, each with multiple findings."""
    data = _minimal_extraction()
    data["assessments"] = [
        {
            "ordinal": 1,
            "assessment_date": "2025-03-19",
            "findings": [
                {
                    "ordinal": 1,
                    "identified_date": "2025-03-19",
                    "due_date": "2025-04-19",
                    "completed_date": None,
                    "state": "Closed",
                    "person_responsible": "RP",
                    "category": {"raw": "Operations : A", "parent": "Operations", "child": "A"},
                    "description_verbatim": "First finding.",
                    "description_summary": None,
                    "summary_bullets": None,
                    "referenced_standards": [],
                    "referenced_urls": [],
                    "source_page_numbers": [1],
                },
                {
                    "ordinal": 2,
                    "identified_date": "2025-03-19",
                    "due_date": "2025-04-19",
                    "completed_date": None,
                    "state": "Closed",
                    "person_responsible": "RP",
                    "category": {"raw": "Operations : B", "parent": "Operations", "child": "B"},
                    "description_verbatim": "Second finding.",
                    "description_summary": None,
                    "summary_bullets": None,
                    "referenced_standards": [],
                    "referenced_urls": [],
                    "source_page_numbers": [2],
                },
            ],
        },
        {
            "ordinal": 2,
            "assessment_date": "2025-04-30",
            "findings": [
                {
                    "ordinal": 1,
                    "identified_date": "2025-04-30",
                    "due_date": "2025-05-30",
                    "completed_date": None,
                    "state": "Closed",
                    "person_responsible": "RP",
                    "category": {"raw": "Operations : A", "parent": "Operations", "child": "A"},
                    "description_verbatim": "Third finding (visit 2).",
                    "description_summary": None,
                    "summary_bullets": None,
                    "referenced_standards": [],
                    "referenced_urls": [],
                    "source_page_numbers": [3],
                },
            ],
        },
    ]

    case = load_extraction_dict(data, db_session)
    db_session.flush()

    assessments = (
        db_session.query(Assessment)
        .filter_by(case_id=case.id)
        .order_by(Assessment.ordinal)
        .all()
    )
    assert len(assessments) == 2
    assert len(assessments[0].__dict__)  # exists
    assert db_session.query(Finding).count() == 3
    # Two distinct categories created (Operations:A and Operations:B), reused across findings
    assert db_session.query(FindingCategory).count() == 2


def test_loads_real_extraction_from_file(db_session, tmp_path):
    """Round-trip: write a JSON file, read it via load_extraction()."""
    from app.ingest.loader import load_extraction

    data = _minimal_extraction()
    json_path = tmp_path / "test.json"
    json_path.write_text(json.dumps(data))

    case = load_extraction(json_path, db_session)
    db_session.flush()

    assert case.case_number == "PP0002449"