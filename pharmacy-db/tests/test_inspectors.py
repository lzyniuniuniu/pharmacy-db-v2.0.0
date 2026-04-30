import pytest
from sqlalchemy.exc import IntegrityError

from app.models.inspector import Inspector
from app.models.regulatory_body import RegulatoryBody


@pytest.fixture
def acp(db_session):
    body = RegulatoryBody(name="Alberta College of Pharmacy", short_name="ACP")
    db_session.add(body)
    db_session.flush()
    return body


def test_can_create_inspector(db_session, acp):
    inspector = Inspector(
        regulatory_body_id=acp.id,
        full_name="Tyler Watson",
        email="tyler.watson@abpharmacy.ca",
        role="Pharmacy Practice Consultant",
    )
    db_session.add(inspector)
    db_session.flush()

    retrieved = db_session.query(Inspector).filter_by(email="tyler.watson@abpharmacy.ca").one()
    assert retrieved.full_name == "Tyler Watson"
    assert retrieved.regulatory_body.short_name == "ACP"


def test_inspector_can_have_only_a_name(db_session, acp):
    """Supervisor-assignment workflow: create a stub with just the name."""
    inspector = Inspector(regulatory_body_id=acp.id, full_name="Mike")
    db_session.add(inspector)
    db_session.flush()
    assert inspector.id is not None
    assert inspector.email is None


def test_inspector_can_have_no_fields_filled_in(db_session, acp):
    """The fully-unknown-but-pending case."""
    inspector = Inspector(regulatory_body_id=acp.id)
    db_session.add(inspector)
    db_session.flush()
    assert inspector.id is not None


def test_duplicate_email_in_same_body_rejected(db_session, acp):
    db_session.add(Inspector(regulatory_body_id=acp.id, email="t@acp.ca", full_name="A"))
    db_session.flush()
    db_session.add(Inspector(regulatory_body_id=acp.id, email="t@acp.ca", full_name="B"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_email_in_different_bodies_allowed(db_session, acp):
    """An inspector who works for two different regulators (rare but legal)."""
    other = RegulatoryBody(name="BC College of Pharmacists", short_name="BCCP")
    db_session.add(other)
    db_session.flush()

    db_session.add(Inspector(regulatory_body_id=acp.id, email="x@example.com", full_name="X"))
    db_session.add(Inspector(regulatory_body_id=other.id, email="x@example.com", full_name="X"))
    db_session.flush()
    assert db_session.query(Inspector).count() == 2


def test_multiple_inspectors_with_null_email_coexist(db_session, acp):
    """Postgres treats NULLs as distinct in unique constraints, so multiple
    'unassigned' inspectors are fine. This is the workflow we want."""
    db_session.add(Inspector(regulatory_body_id=acp.id, full_name="Pending One"))
    db_session.add(Inspector(regulatory_body_id=acp.id, full_name="Pending Two"))
    db_session.flush()  # should NOT raise
    assert db_session.query(Inspector).count() == 2


def test_cannot_delete_regulatory_body_with_inspectors(db_session, acp):
    db_session.add(Inspector(regulatory_body_id=acp.id, full_name="Tyler Watson"))
    db_session.flush()

    db_session.delete(acp)
    with pytest.raises(IntegrityError):
        db_session.flush()


# =========================== API tests ===========================
def _create_acp(client) -> str:
    r = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"})
    assert r.status_code == 201
    return r.json()["id"]


def test_create_inspector_via_api(client):
    body_id = _create_acp(client)
    response = client.post(
        "/inspectors",
        json={
            "regulatory_body_id": body_id,
            "full_name": "Tyler Watson",
            "email": "tyler.watson@abpharmacy.ca",
            "role": "Pharmacy Practice Consultant",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Tyler Watson"
    assert body["email"] == "tyler.watson@abpharmacy.ca"


def test_create_inspector_with_only_name(client):
    """Supervisor will fill in details later — should be allowed."""
    body_id = _create_acp(client)
    response = client.post(
        "/inspectors",
        json={"regulatory_body_id": body_id, "full_name": "Mike"},
    )
    assert response.status_code == 201
    assert response.json()["email"] is None


def test_invalid_email_rejected_at_api(client):
    body_id = _create_acp(client)
    response = client.post(
        "/inspectors",
        json={"regulatory_body_id": body_id, "email": "not-an-email", "full_name": "X"},
    )
    # Pydantic validation failure returns 422, not 400.
    assert response.status_code == 422


def test_create_inspector_with_unknown_regulator_returns_404(client):
    fake = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/inspectors",
        json={"regulatory_body_id": fake, "full_name": "X"},
    )
    assert response.status_code == 404


def test_duplicate_email_returns_409(client):
    body_id = _create_acp(client)
    payload = {"regulatory_body_id": body_id, "email": "t@acp.ca", "full_name": "A"}
    client.post("/inspectors", json=payload)
    response = client.post("/inspectors", json={**payload, "full_name": "B"})
    assert response.status_code == 409


def test_unassigned_only_filter(client):
    body_id = _create_acp(client)
    client.post("/inspectors", json={"regulatory_body_id": body_id, "full_name": "Has Email", "email": "e@x.com"})
    client.post("/inspectors", json={"regulatory_body_id": body_id, "full_name": "No Email A"})
    client.post("/inspectors", json={"regulatory_body_id": body_id, "full_name": "No Email B"})

    all_inspectors = client.get("/inspectors").json()
    assert len(all_inspectors) == 3

    unassigned = client.get(f"/inspectors?regulatory_body_id={body_id}&unassigned_only=true").json()
    assert len(unassigned) == 2
    assert {i["full_name"] for i in unassigned} == {"No Email A", "No Email B"}


def test_patch_inspector_assigns_email(client):
    """The supervisor-assignment workflow in action."""
    body_id = _create_acp(client)
    create_resp = client.post(
        "/inspectors",
        json={"regulatory_body_id": body_id, "full_name": "Mike"},
    )
    inspector_id = create_resp.json()["id"]

    # Supervisor fills in the missing details
    response = client.patch(
        f"/inspectors/{inspector_id}",
        json={"email": "mike@acp.ca", "role": "Pharmacy Practice Consultant"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "mike@acp.ca"
    assert body["role"] == "Pharmacy Practice Consultant"
    assert body["full_name"] == "Mike"  # unchanged