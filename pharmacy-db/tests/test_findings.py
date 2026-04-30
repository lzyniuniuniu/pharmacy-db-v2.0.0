from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.assessment import Assessment
from app.models.case import Case
from app.models.document import Document
from app.models.finding import Finding
from app.models.finding_category import FindingCategory
from app.models.regulatory_body import RegulatoryBody


@pytest.fixture
def acp(db_session):
    body = RegulatoryBody(name="Alberta College of Pharmacy", short_name="ACP")
    db_session.add(body)
    db_session.flush()
    return body


@pytest.fixture
def case_pp0002449(db_session, acp):
    case = Case(regulatory_body_id=acp.id, case_number="PP0002449")
    db_session.add(case)
    db_session.flush()
    return case


@pytest.fixture
def assessment_1(db_session, case_pp0002449):
    assessment = Assessment(
        case_id=case_pp0002449.id,
        ordinal=1,
        assessment_date=date(2025, 3, 19),
    )
    db_session.add(assessment)
    db_session.flush()
    return assessment


@pytest.fixture
def category_injections(db_session, acp):
    category = FindingCategory(
        regulatory_body_id=acp.id,
        full_path="Operations : Injections",
    )
    db_session.add(category)
    db_session.flush()
    return category


def _make_finding(assessment, case, **overrides) -> Finding:
    """Helper: a valid Finding with sensible defaults."""
    defaults = {
        "assessment_id": assessment.id,
        "case_id": case.id,
        "ordinal": 1,
        "description_verbatim": "Sample finding text for testing.",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def test_can_create_minimal_finding(db_session, case_pp0002449, assessment_1):
    finding = _make_finding(assessment_1, case_pp0002449)
    db_session.add(finding)
    db_session.flush()
    assert finding.id is not None


def test_can_create_full_finding(db_session, case_pp0002449, assessment_1, category_injections):
    finding = _make_finding(
        assessment_1, case_pp0002449,
        category_id=category_injections.id,
        identified_date=date(2025, 3, 19),
        due_date=date(2025, 4, 19),
        completed_date=date(2025, 4, 8),
        state="Closed",
        person_responsible="Rebecca Perrin",
        category_raw="Operations : Injections",
        description_verbatim="Review the following reference regarding emergency anaphylaxis kits.",
        referenced_standards=[
            {"raw_text": "Standard 6.5 of the SOLP", "standard_code": "6.5", "document": "SOLP"},
        ],
        referenced_urls=["https://abpharmacy.ca/news/acp-launches-cqi/"],
        source_page_numbers=[2],
    )
    db_session.add(finding)
    db_session.flush()

    retrieved = db_session.query(Finding).one()
    assert retrieved.state == "Closed"
    assert retrieved.referenced_standards[0]["standard_code"] == "6.5"
    assert retrieved.referenced_urls == ["https://abpharmacy.ca/news/acp-launches-cqi/"]
    assert retrieved.source_page_numbers == [2]
    assert retrieved.category.full_path == "Operations : Injections"


def test_jsonb_referenced_standards_roundtrip(db_session, case_pp0002449, assessment_1):
    """Ensure the JSONB list-of-objects survives storage and retrieval."""
    references = [
        {"raw_text": "NAPRA 5.1.2.2", "standard_code": "5.1.2.2", "document": "NAPRA"},
        {"raw_text": "Section 4.5.1 of the SOLP", "standard_code": "4.5.1", "document": "SOLP"},
    ]
    finding = _make_finding(assessment_1, case_pp0002449, referenced_standards=references)
    db_session.add(finding)
    db_session.flush()

    retrieved = db_session.query(Finding).one()
    assert len(retrieved.referenced_standards) == 2
    assert retrieved.referenced_standards[1]["document"] == "SOLP"


def test_array_columns_roundtrip(db_session, case_pp0002449, assessment_1):
    """ARRAY(Text) and ARRAY(Integer) preserve order and content."""
    finding = _make_finding(
        assessment_1, case_pp0002449,
        referenced_urls=["https://example.com/a", "https://example.com/b"],
        source_page_numbers=[7, 8, 9],
        summary_bullets=["First point", "Second point"],
    )
    db_session.add(finding)
    db_session.flush()

    retrieved = db_session.query(Finding).one()
    assert retrieved.referenced_urls == ["https://example.com/a", "https://example.com/b"]
    assert retrieved.source_page_numbers == [7, 8, 9]
    assert retrieved.summary_bullets == ["First point", "Second point"]


def test_assessment_can_have_multiple_findings(db_session, case_pp0002449, assessment_1):
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=1, description_verbatim="A"))
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=2, description_verbatim="B"))
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=3, description_verbatim="C"))
    db_session.flush()
    assert db_session.query(Finding).count() == 3


def test_duplicate_ordinal_within_assessment_rejected(db_session, case_pp0002449, assessment_1):
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=1, description_verbatim="A"))
    db_session.flush()
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=1, description_verbatim="B"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_assessment_cascades_to_findings(db_session, case_pp0002449, assessment_1):
    """CASCADE: deleting the parent assessment removes its findings."""
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=1))
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=2))
    db_session.flush()
    assert db_session.query(Finding).count() == 2

    db_session.delete(assessment_1)
    db_session.flush()
    assert db_session.query(Finding).count() == 0


def test_deleting_case_cascades_to_findings(db_session, case_pp0002449, assessment_1):
    """CASCADE through assessments AND directly via case_id FK."""
    db_session.add(_make_finding(assessment_1, case_pp0002449, ordinal=1))
    db_session.flush()

    db_session.delete(case_pp0002449)
    db_session.flush()
    assert db_session.query(Finding).count() == 0


def test_cannot_delete_category_with_findings(db_session, case_pp0002449, assessment_1, category_injections):
    """RESTRICT: a category can't be deleted while findings reference it."""
    db_session.add(_make_finding(
        assessment_1, case_pp0002449,
        category_id=category_injections.id,
    ))
    db_session.flush()

    db_session.delete(category_injections)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_source_document_sets_finding_link_null(db_session, case_pp0002449, assessment_1):
    """SET NULL: deleting the source document leaves findings, just unlinked."""
    document = Document(
        document_type="case_summary",
        file_hash="sha256:" + "a" * 64,
        file_name="report.pdf",
    )
    db_session.add(document)
    db_session.flush()

    finding = _make_finding(assessment_1, case_pp0002449, source_document_id=document.id)
    db_session.add(finding)
    db_session.flush()
    finding_id = finding.id

    db_session.delete(document)
    db_session.flush()
    db_session.expire(finding)

    surviving = db_session.get(Finding, finding_id)
    assert surviving is not None
    assert surviving.source_document_id is None


def test_full_text_search_matches_description(db_session, case_pp0002449, assessment_1):
    """Verify the generated tsvector + GIN index actually finds matches."""
    db_session.add(_make_finding(
        assessment_1, case_pp0002449, ordinal=1,
        description_verbatim="Review the anaphylaxis kit and epinephrine dosing.",
    ))
    db_session.add(_make_finding(
        assessment_1, case_pp0002449, ordinal=2,
        description_verbatim="Update narcotic destruction documentation.",
    ))
    db_session.add(_make_finding(
        assessment_1, case_pp0002449, ordinal=3,
        description_verbatim="Ensure cold chain is maintained for refrigerated medications.",
    ))
    db_session.flush()

    # Search using Postgres full-text search syntax
    result = db_session.execute(
        text("""
            SELECT ordinal FROM findings
            WHERE description_tsv @@ plainto_tsquery('english', :q)
            ORDER BY ordinal
        """),
        {"q": "narcotic"},
    ).fetchall()
    assert [r.ordinal for r in result] == [2]

    # Verify stemming works: 'medications' should match 'medication'
    result = db_session.execute(
        text("""
            SELECT ordinal FROM findings
            WHERE description_tsv @@ plainto_tsquery('english', :q)
            ORDER BY ordinal
        """),
        {"q": "medication"},
    ).fetchall()
    assert [r.ordinal for r in result] == [3]


def test_full_text_search_updates_when_description_changes(db_session, case_pp0002449, assessment_1):
    """Generated columns must update when their source changes."""
    finding = _make_finding(
        assessment_1, case_pp0002449,
        description_verbatim="Original text about temperatures.",
    )
    db_session.add(finding)
    db_session.flush()

    # Verify initial search works
    initial = db_session.execute(
        text("SELECT id FROM findings WHERE description_tsv @@ plainto_tsquery('english', 'temperature')"),
    ).fetchall()
    assert len(initial) == 1

    # Update the description
    finding.description_verbatim = "Now we discuss narcotic management instead."
    db_session.flush()

    # Old search no longer matches
    old_result = db_session.execute(
        text("SELECT id FROM findings WHERE description_tsv @@ plainto_tsquery('english', 'temperature')"),
    ).fetchall()
    assert len(old_result) == 0

    # New search matches
    new_result = db_session.execute(
        text("SELECT id FROM findings WHERE description_tsv @@ plainto_tsquery('english', 'narcotic')"),
    ).fetchall()
    assert len(new_result) == 1


# ====================== API tests ======================

def _setup(client) -> dict[str, str]:
    """Create the standard chain via the API: ACP, case, assessment, category."""
    body = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"}).json()
    case = client.post("/cases", json={
        "case_number": "PP0002449", "regulatory_body_id": body["id"],
    }).json()
    assessment = client.post("/assessments", json={
        "case_id": case["id"], "ordinal": 1, "assessment_date": "2025-03-19",
    }).json()
    category = client.post("/finding-categories", json={
        "regulatory_body_id": body["id"], "full_path": "Operations : Injections",
    }).json()
    return {
        "body_id": body["id"],
        "case_id": case["id"],
        "assessment_id": assessment["id"],
        "category_id": category["id"],
    }


def test_create_finding_via_api(client):
    ids = _setup(client)
    response = client.post(
        "/findings",
        json={
            "assessment_id": ids["assessment_id"],
            "case_id": ids["case_id"],
            "ordinal": 1,
            "description_verbatim": "Review anaphylaxis kit and epinephrine dosing.",
            "category_id": ids["category_id"],
            "category_raw": "Operations : Injections",
            "state": "Closed",
            "person_responsible": "Rebecca Perrin",
            "identified_date": "2025-03-19",
            "due_date": "2025-04-19",
            "completed_date": "2025-04-08",
            "referenced_standards": [
                {"raw_text": "Standard 6.5 of the SOLP", "standard_code": "6.5", "document": "SOLP"},
            ],
            "referenced_urls": ["https://abpharmacy.ca/news/acp-launches-cqi/"],
            "source_page_numbers": [2],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "Closed"
    assert body["category"]["full_path"] == "Operations : Injections"
    assert body["category"]["parent"] == "Operations"
    assert body["referenced_urls"] == ["https://abpharmacy.ca/news/acp-launches-cqi/"]
    assert body["referenced_standards"][0]["standard_code"] == "6.5"


def test_create_finding_with_mismatched_case_returns_400(client):
    """assessment_id and case_id must agree."""
    ids = _setup(client)
    other_case = client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
    }).json()

    response = client.post(
        "/findings",
        json={
            "assessment_id": ids["assessment_id"],
            "case_id": other_case["id"],  # WRONG — assessment is in a different case
            "ordinal": 1,
            "description_verbatim": "Test",
        },
    )
    assert response.status_code == 400


def test_create_finding_with_unknown_assessment_returns_404(client):
    ids = _setup(client)
    fake = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/findings",
        json={
            "assessment_id": fake,
            "case_id": ids["case_id"],
            "ordinal": 1,
            "description_verbatim": "Test",
        },
    )
    assert response.status_code == 404


def test_duplicate_ordinal_returns_409(client):
    ids = _setup(client)
    payload = {
        "assessment_id": ids["assessment_id"],
        "case_id": ids["case_id"],
        "ordinal": 1,
        "description_verbatim": "Test",
    }
    client.post("/findings", json=payload)
    response = client.post("/findings", json={**payload, "description_verbatim": "Other"})
    assert response.status_code == 409


def test_list_findings_filters_by_case(client):
    ids = _setup(client)
    other_case = client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
    }).json()
    other_assessment = client.post("/assessments", json={
        "case_id": other_case["id"], "ordinal": 1,
    }).json()

    client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 1, "description_verbatim": "Finding in case A",
    })
    client.post("/findings", json={
        "assessment_id": other_assessment["id"], "case_id": other_case["id"],
        "ordinal": 1, "description_verbatim": "Finding in case B",
    })

    case_a_findings = client.get(f"/findings?case_id={ids['case_id']}").json()
    assert len(case_a_findings) == 1
    assert "case A" in case_a_findings[0]["description_verbatim"]


def test_full_text_search_via_api(client):
    """The search query parameter does what's claimed."""
    ids = _setup(client)
    client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 1, "description_verbatim": "Anaphylaxis kit needs epinephrine.",
    })
    client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 2, "description_verbatim": "Update narcotic destruction documentation.",
    })
    client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 3, "description_verbatim": "Maintain cold chain for medications.",
    })

    # Direct match
    results = client.get("/findings?search=narcotic").json()
    assert len(results) == 1
    assert results[0]["ordinal"] == 2

    # Stemmed match: "medication" finds "medications"
    results = client.get("/findings?search=medication").json()
    assert len(results) == 1
    assert results[0]["ordinal"] == 3

    # No match
    results = client.get("/findings?search=spaceship").json()
    assert len(results) == 0


def test_search_combined_with_other_filters(client):
    """Search + case filter compose correctly."""
    ids = _setup(client)
    other_case = client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
    }).json()
    other_assessment = client.post("/assessments", json={
        "case_id": other_case["id"], "ordinal": 1,
    }).json()

    # Both contain "narcotic" but in different cases
    client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 1, "description_verbatim": "Narcotic destruction in case A.",
    })
    client.post("/findings", json={
        "assessment_id": other_assessment["id"], "case_id": other_case["id"],
        "ordinal": 1, "description_verbatim": "Narcotic safety in case B.",
    })

    # Search across all
    all_results = client.get("/findings?search=narcotic").json()
    assert len(all_results) == 2

    # Search filtered to one case
    one_case = client.get(f"/findings?search=narcotic&case_id={ids['case_id']}").json()
    assert len(one_case) == 1
    assert "case A" in one_case[0]["description_verbatim"]


def test_patch_finding_adds_summary(client):
    """A common workflow: LLM populates description_summary after creation."""
    ids = _setup(client)
    create = client.post("/findings", json={
        "assessment_id": ids["assessment_id"], "case_id": ids["case_id"],
        "ordinal": 1, "description_verbatim": "Long verbatim text here.",
    })
    finding_id = create.json()["id"]
    assert create.json()["description_summary"] is None

    response = client.patch(f"/findings/{finding_id}", json={
        "description_summary": "Short LLM-generated summary.",
        "summary_bullets": ["Point 1", "Point 2", "Point 3"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["description_summary"] == "Short LLM-generated summary."
    assert body["summary_bullets"] == ["Point 1", "Point 2", "Point 3"]
    # Verbatim text unchanged
    assert body["description_verbatim"] == "Long verbatim text here."