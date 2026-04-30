import pytest
from sqlalchemy.exc import IntegrityError

from app.models.pharmacy import Pharmacy
from app.models.regulatory_body import RegulatoryBody

@pytest.fixture
def acp(db_session):
    """Reusable: an ACP regulatory body in the test database."""
    body = RegulatoryBody(name="Alberta College of Pharmacy", short_name="ACP")
    db_session.add(body)
    db_session.flush()
    return body

def test_can_create_pharmacy(db_session, acp):
    pharmacy = Pharmacy(
        regulatory_body_id=acp.id,
        license_number="3538",
        name="Mint Health + Drugs: Beaverlodge",
    )
    db_session.add(pharmacy)
    db_session.flush()

    retrieved = db_session.query(Pharmacy).filter_by(license_number="3538").one()
    assert retrieved.name == "Mint Health + Drugs: Beaverlodge"
    assert retrieved.regulatory_body_id == acp.id
    assert retrieved.regulatory_body.short_name == "ACP"

def test_pharmacy_can_have_null_name_and_license(db_session, acp):
    pharmacy = Pharmacy(regulatory_body_id=acp.id, license_number=None, name=None)
    db_session.add(pharmacy)
    db_session.flush()

    assert pharmacy.id is not None


def test_duplicate_license_in_same_body_rejected(db_session, acp):
    db_session.add(Pharmacy(regulatory_body_id=acp.id, license_number="3538", name="A"))
    db_session.flush()
    db_session.add(Pharmacy(regulatory_body_id=acp.id, license_number="3538", name="B"))
    with pytest.raises(IntegrityError):
        db_session.flush()

def test_same_license_in_different_bodies_allowed(db_session, acp):
    """Two different regulators can independently issue license "3538"."""
    other_body = RegulatoryBody(name="British Columbia College of Pharmacists", short_name="BCCP")
    db_session.add(other_body)
    db_session.flush()

    db_session.add(Pharmacy(regulatory_body_id=acp.id, license_number="3538", name="A"))
    db_session.add(Pharmacy(regulatory_body_id=other_body.id, license_number="3538", name="B"))
    db_session.flush()

    assert db_session.query(Pharmacy).count() == 2

def test_cannot_delete_regulatory_body_with_pharmacies(db_session, acp):
    """ondelete='RESTRICT' should prevent orphaning pharmacies."""
    db_session.add(Pharmacy(regulatory_body_id=acp.id, license_number="3538", name="A"))
    db_session.flush()

    db_session.delete(acp)
    with pytest.raises(IntegrityError):
        db_session.flush()



# ============================= API tests =============================
def _create_acp(client) -> str:
    """Helper: create the ACP regulatory body via the API and return its ID."""
    r = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"})
    assert r.status_code == 201
    return r.json()["id"]

def test_create_pharmacy_via_api(client):
    body_id = _create_acp(client)

    reponse = client.post(
        "/pharmacies",
        json={
            "regulatory_body_id": body_id,
            "license_number": "3538",
            "name": "Mint Health + Drugs: Beaverlodge",
        },
    )
    assert reponse.status_code == 201
    p = reponse.json()
    assert p["license_number"] == "3538"
    assert p["regulatory_body_id"] == body_id

def test_create_pharmacy_with_unknown_regulator_returns_404(client):
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/pharmacies",
        json={"regulatory_body_id": fake_uuid, "license_number": "X"},
    )
    assert response.status_code == 404


def test_duplicate_license_returns_409(client):
    body_id = _create_acp(client)
    payload = {"regulatory_body_id": body_id, "license_number": "3538", "name": "A"}
    client.post("/pharmacies", json=payload)
    response = client.post("/pharmacies", json={**payload, "name": "B"})
    assert response.status_code == 409


def test_list_pharmacies_filters_by_regulatory_body(client):
    body_a = _create_acp(client)
    body_b = client.post("/regulatory-bodies", json={"name": "BCCP", "short_name": "BCCP"}).json()["id"]

    client.post("/pharmacies", json={"regulatory_body_id": body_a, "license_number": "1", "name": "Alpha"})
    client.post("/pharmacies", json={"regulatory_body_id": body_a, "license_number": "2", "name": "Beta"})
    client.post("/pharmacies", json={"regulatory_body_id": body_b, "license_number": "3", "name": "Gamma"})

    all_pharmacies = client.get("/pharmacies").json()
    assert len(all_pharmacies) == 3

    only_a = client.get(f"/pharmacies?regulatory_body_id={body_a}").json()
    assert len(only_a) == 2
    assert {p["name"] for p in only_a} == {"Alpha", "Beta"}


def test_patch_pharmacy_updates_only_provided_fields(client):
    body_id = _create_acp(client)
    create_resp = client.post(
        "/pharmacies",
        json={"regulatory_body_id": body_id, "license_number": "3538", "name": "Original Name"},
    )
    pharmacy_id = create_resp.json()["id"]

    # Update only the name
    response = client.patch(f"/pharmacies/{pharmacy_id}", json={"name": "Updated Name"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated Name"
    assert body["license_number"] == "3538"  # unchanged


def test_get_unknown_pharmacy_returns_404(client):
    response = client.get("/pharmacies/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404