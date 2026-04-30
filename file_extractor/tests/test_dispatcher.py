"""Tests for the document type dispatcher in extract.py."""
from pathlib import Path

import pytest

from extract import (
    AmbiguousMatch,  # noqa: F401  (kept for future tests)
    NoMatchingExtractor,
    extract,
    select_extractor,
)
from extractors.inspection import InspectionExtractor


def test_inspection_pdf_classified_correctly(sample_pdf: Path):
    """An ACP case summary PDF should be picked up by the InspectionExtractor."""
    extractor = select_extractor(sample_pdf)
    assert isinstance(extractor, InspectionExtractor)
    assert extractor.DOCUMENT_TYPE == "case_summary"


def test_extraction_pipeline_end_to_end(sample_pdf: Path):
    """Full extraction via the dispatcher returns a valid JSON dict."""
    result = extract(sample_pdf)
    assert result["case"]["case_number"] == "PP0002449"
    assert result["extraction_metadata"]["validation_status"] in (
        "passed",
        "passed_with_warnings",
    )


def test_force_type_overrides_detection(sample_pdf: Path):
    """force_type bypasses can_handle()."""
    extractor = select_extractor(sample_pdf, force_type="case_summary")
    assert isinstance(extractor, InspectionExtractor)


def test_force_type_unknown_raises(sample_pdf: Path):
    with pytest.raises(NoMatchingExtractor, match="No extractor registered"):
        select_extractor(sample_pdf, force_type="not_a_real_type")


def test_unrecognized_pdf_raises_no_matching_extractor(tmp_path: Path):
    """A PDF that doesn't match any registered extractor should fail clearly."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    fake_pdf = tmp_path / "not_an_inspection.pdf"
    c = canvas.Canvas(str(fake_pdf), pagesize=letter)
    c.drawString(100, 750, "This is a random document with no inspection markers.")
    c.drawString(100, 730, "It mentions nothing about pharmacies or ACP.")
    c.save()

    with pytest.raises(NoMatchingExtractor):
        select_extractor(fake_pdf)
