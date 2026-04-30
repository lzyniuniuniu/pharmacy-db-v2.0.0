import pytest
from datetime import date
from sqlalchemy.exc import IntegrityError

from app.models.case import Case
from app.models.document import Document
from app.models.inspector import Inspector
from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody


@pytest.fixture
def acp(db_session):
    body = RegulatoryBody(name="Alberta College of Pharmacy", short_name="ACP")
    db_session.add(body)
    db_session.flush()
    return body


@pytest.fixture
def beaverlodge(db_session, acp):
    pharmacy = Pharmacy(
        regulatory_body_id=acp.id,
        license_number="3538",
        name="Mint Health + Drugs: Beaverlodge",
    )
    db_session.add(pharmacy)
    db_session.flush()
    return pharmacy


@pytest.fixture
def tyler(db_session, acp):
    inspector = Inspector(
        regulatory_body_id=acp.id,
        full_name="Tyler Watson",
        email="tyler.watson@abpharmacy.ca",
        role="Pharmacy Practice Consultant",
    )
    db_session.add(inspector)
    db_session.flush()
    return inspector


def test_can_create_full_case(db_session, acp, beaverlodge, tyler):
    case = Case(
        regulatory_body_id=acp.id,
        case_number="PP0002449",
        pharmacy_id=beaverlodge.id,
        consultant_id=tyler.id,
        case_type="Routine",
        case_state="Work in Progress",
        licensee_name="Rebecca Perrin",
        licensee_email="becky.p@mintdrugs.com",
        consultant_assignment_status="confirmed",
    )
    db_session.add(case)
    db_session.flush()

    retrieved = db_session.query(Case).filter_by(case_number="PP0002449").one()
    assert retrieved.pharmacy.name == "Mint Health + Drugs: Beaverlodge"
    assert retrieved.consultant.full_name == "Tyler Watson"
    assert retrieved.regulatory_body.short_name == "ACP"


def test_can_create_case_with_only_required_fields(db_session, acp):
    """The SCL workflow: case exists, pharmacy/consultant unknown."""
    case = Case(
        regulatory_body_id=acp.id,
        case_number="PP0001972",
        consultant_assignment_status="unknown",
    )
    db_session.add(case)
    db_session.flush()
    assert case.id is not None
    assert case.pharmacy_id is None
    assert case.consultant_id is None


def test_consultant_assignment_status_defaults_to_unknown(db_session, acp):
    """If you don't specify it, the status is 'unknown'."""
    case = Case(regulatory_body_id=acp.id, case_number="PP0000001")
    db_session.add(case)
    db_session.flush()
    db_session.refresh(case)
    assert case.consultant_assignment_status == "unknown"


def test_case_number_must_be_unique_within_regulator(db_session, acp):
    db_session.add(Case(regulatory_body_id=acp.id, case_number="PP0002449"))
    db_session.flush()
    db_session.add(Case(regulatory_body_id=acp.id, case_number="PP0002449"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_case_number_in_different_regulators_allowed(db_session, acp):
    """Two regulators could coincidentally use the same numbering scheme."""
    other = RegulatoryBody(name="BCCP", short_name="BCCP")
    db_session.add(other)
    db_session.flush()

    db_session.add(Case(regulatory_body_id=acp.id, case_number="PP0002449"))
    db_session.add(Case(regulatory_body_id=other.id, case_number="PP0002449"))
    db_session.flush()  # should NOT raise
    assert db_session.query(Case).count() == 2


def test_cannot_delete_pharmacy_with_cases(db_session, acp, beaverlodge):
    case = Case(
        regulatory_body_id=acp.id,
        case_number="PP0002449",
        pharmacy_id=beaverlodge.id,
    )
    db_session.add(case)
    db_session.flush()

    db_session.delete(beaverlodge)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cannot_delete_consultant_with_cases(db_session, acp, tyler):
    case = Case(
        regulatory_body_id=acp.id,
        case_number="PP0002449",
        consultant_id=tyler.id,
    )
    db_session.add(case)
    db_session.flush()

    db_session.delete(tyler)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_document_can_be_linked_to_case(db_session, acp):
    case = Case(regulatory_body_id=acp.id, case_number="PP0002449")
    db_session.add(case)
    db_session.flush()

    document = Document(
        document_type="case_summary",
        file_hash="sha256:" + "a" * 64,
        file_name="report.pdf",
        case_id=case.id,
    )
    db_session.add(document)
    db_session.flush()

    assert document.case_id == case.id
    assert document.case.case_number == "PP0002449"  # type: ignore[union-attr]


def test_deleting_case_orphans_documents_not_deletes_them(db_session, acp):
    """ondelete='SET NULL' on documents.case_id: case deletion preserves the
    file record but unlinks it."""
    case = Case(regulatory_body_id=acp.id, case_number="PP0002449")
    db_session.add(case)
    db_session.flush()

    document = Document(
        document_type="case_summary",
        file_hash="sha256:" + "b" * 64,
        file_name="report.pdf",
        case_id=case.id,
    )
    db_session.add(document)
    db_session.flush()
    document_id = document.id

    db_session.delete(case)
    db_session.flush()
    db_session.expire_all()  # discard cached state so we re-read from the DB

    # Document still exists
    surviving = db_session.get(Document, document_id)
    assert surviving is not None
    # But its case_id is now NULL
    assert surviving.case_id is None


def test_case_can_have_multiple_documents(db_session, acp):
    """Re-generated PDFs of the same case all link to the case."""
    case = Case(regulatory_body_id=acp.id, case_number="PP0002449")
    db_session.add(case)
    db_session.flush()

    db_session.add(Document(
        document_type="case_summary",
        file_hash="sha256:" + "c" * 64,
        file_name="report_v1.pdf",
        case_id=case.id,
    ))
    db_session.add(Document(
        document_type="case_summary",
        file_hash="sha256:" + "d" * 64,
        file_name="report_v2.pdf",
        case_id=case.id,
    ))
    db_session.flush()

    docs = db_session.query(Document).filter(Document.case_id == case.id).all()
    assert len(docs) == 2


def _setup(client) -> dict[str, str]:
    """Helper: create the standard ACP + pharmacy + inspector. Returns ids."""
    body = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"}).json()
    pharmacy = client.post(
        "/pharmacies",
        json={"regulatory_body_id": body["id"], "license_number": "3538", "name": "Beaverlodge"},
    ).json()
    inspector = client.post(
        "/inspectors",
        json={"regulatory_body_id": body["id"], "full_name": "Tyler Watson", "email": "t@acp.ca"},
    ).json()
    return {"body_id": body["id"], "pharmacy_id": pharmacy["id"], "inspector_id": inspector["id"]}


def test_create_full_case_via_api(client):
    ids = _setup(client)
    response = client.post(
        "/cases",
        json={
            "case_number": "PP0002449",
            "regulatory_body_id": ids["body_id"],
            "pharmacy_id": ids["pharmacy_id"],
            "consultant_id": ids["inspector_id"],
            "case_type": "Routine",
            "case_state": "Work in Progress",
            "licensee_name": "Rebecca Perrin",
            "licensee_email": "becky.p@mintdrugs.com",
            "consultant_assignment_status": "confirmed",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["case_number"] == "PP0002449"
    # Nested objects in the response
    assert body["licensee"] == {"name": "Rebecca Perrin", "email": "becky.p@mintdrugs.com"}
    assert body["consultant"]["full_name"] == "Tyler Watson"
    assert body["consultant"]["id"] == ids["inspector_id"]


def test_create_case_with_unknown_pharmacy_returns_404(client):
    ids = _setup(client)
    fake = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/cases",
        json={
            "case_number": "PP0001",
            "regulatory_body_id": ids["body_id"],
            "pharmacy_id": fake,
        },
    )
    assert response.status_code == 404
    assert "pharmacy" in response.json()["detail"].lower()


def test_duplicate_case_number_returns_409(client):
    ids = _setup(client)
    payload = {"case_number": "PP0002449", "regulatory_body_id": ids["body_id"]}
    client.post("/cases", json=payload)
    response = client.post("/cases", json=payload)
    assert response.status_code == 409


def test_create_case_with_minimum_fields(client):
    """The SCL workflow: case exists with no pharmacy/consultant info."""
    ids = _setup(client)
    response = client.post(
        "/cases",
        json={"case_number": "PP0001972", "regulatory_body_id": ids["body_id"]},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["pharmacy_id"] is None
    assert body["consultant"] is None
    assert body["consultant_assignment_status"] == "unknown"


def test_list_cases_filters(client):
    ids = _setup(client)
    other_pharmacy = client.post(
        "/pharmacies",
        json={"regulatory_body_id": ids["body_id"], "license_number": "9999", "name": "Other"},
    ).json()

    client.post("/cases", json={
        "case_number": "PP01", "regulatory_body_id": ids["body_id"],
        "pharmacy_id": ids["pharmacy_id"], "case_state": "Closed",
    })
    client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
        "pharmacy_id": ids["pharmacy_id"], "case_state": "Work in Progress",
    })
    client.post("/cases", json={
        "case_number": "PP03", "regulatory_body_id": ids["body_id"],
        "pharmacy_id": other_pharmacy["id"],
    })

    all_cases = client.get("/cases").json()
    assert len(all_cases) == 3

    by_pharmacy = client.get(f"/cases?pharmacy_id={ids['pharmacy_id']}").json()
    assert len(by_pharmacy) == 2

    by_state = client.get("/cases?case_state=Closed").json()
    assert len(by_state) == 1
    assert by_state[0]["case_number"] == "PP01"


def test_needs_assignment_filter(client):
    ids = _setup(client)
    # Fully assigned
    client.post("/cases", json={
        "case_number": "PP01", "regulatory_body_id": ids["body_id"],
        "pharmacy_id": ids["pharmacy_id"], "consultant_id": ids["inspector_id"],
    })
    # Missing consultant
    client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
        "pharmacy_id": ids["pharmacy_id"],
    })
    # Missing both
    client.post("/cases", json={
        "case_number": "PP03", "regulatory_body_id": ids["body_id"],
    })

    pending = client.get("/cases?needs_assignment=true").json()
    assert len(pending) == 2
    case_numbers = {c["case_number"] for c in pending}
    assert case_numbers == {"PP02", "PP03"}


def test_assign_consultant_endpoint(client):
    """Supervisor assigns a consultant to a case awaiting one."""
    ids = _setup(client)
    create = client.post("/cases", json={
        "case_number": "PP01",
        "regulatory_body_id": ids["body_id"],
    })
    case_id = create.json()["id"]
    assert create.json()["consultant_assignment_status"] == "unknown"

    response = client.post(
        f"/cases/{case_id}/assign-consultant",
        params={"consultant_id": ids["inspector_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["consultant"]["id"] == ids["inspector_id"]
    assert body["consultant_assignment_status"] == "supervisor_assigned"


def test_patch_case_updates_state(client):
    ids = _setup(client)
    create = client.post("/cases", json={
        "case_number": "PP01", "regulatory_body_id": ids["body_id"],
        "case_state": "Work in Progress",
    })
    case_id = create.json()["id"]

    response = client.patch(
        f"/cases/{case_id}",
        json={"case_state": "Closed", "case_closed_date": "2025-04-08"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["case_state"] == "Closed"
    assert body["case_closed_date"] == "2025-04-08"
    assert body["case_number"] == "PP01"  # unchanged