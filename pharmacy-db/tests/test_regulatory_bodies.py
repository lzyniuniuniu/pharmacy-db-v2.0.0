from app.models.regulatory_body import RegulatoryBody


def test_can_create_and_query_regulatory_body(db_session):
    body = RegulatoryBody(
        name="Alberta College of Pharmacy",
        short_name="ACP",
        jurisdiction="Alberta, Canada",
    )
    db_session.add(body)
    db_session.flush()  # assigns the UUID

    retrieved = db_session.query(RegulatoryBody).filter_by(short_name="ACP").one()
    assert retrieved.name == "Alberta College of Pharmacy"
    assert retrieved.jurisdiction == "Alberta, Canada"
    assert retrieved.id is not None
    assert retrieved.created_at is not None


def test_short_name_must_be_unique(db_session):
    db_session.add(RegulatoryBody(name="ACP One", short_name="ACP"))
    db_session.flush()
    db_session.add(RegulatoryBody(name="ACP Two", short_name="ACP"))

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.flush()

def test_create_regulatory_body_via_api(client):
    response = client.post(
        "/regulatory-bodies",
        json={
            "name": "Alberta College of Pharmacy",
            "short_name": "ACP",
            "jurisdiction": "Alberta",
        }
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alberta College of Pharmacy"
    assert body["short_name"] == "ACP"
    assert "id" in body

def test_list_regulatory_bodies(client):
    client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"})
    client.post("/regulatory-bodies", json={"name": "BC College", "short_name": "BCC"})

    response = client.get("/regulatory-bodies")
    assert response.status_code == 200
    bodies = response.json()
    assert len(bodies) == 2


def test_duplicate_short_name_returns_409(client):
    client.post("/regulatory-bodies", json={"name": "First", "short_name": "ACP"})
    response = client.post("/regulatory-bodies", json={"name": "Second", "short_name": "ACP"})
    assert response.status_code == 409