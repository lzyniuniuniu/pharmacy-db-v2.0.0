import pytest
from sqlalchemy.exc import IntegrityError

from app.models.finding_category import FindingCategory
from app.models.regulatory_body import RegulatoryBody
from app.services.finding_categories import get_or_create_category


@pytest.fixture
def acp(db_session):
    body = RegulatoryBody(name="Alberta College of Pharmacy", short_name="ACP")
    db_session.add(body)
    db_session.flush()
    return body


def test_can_create_category(db_session, acp):
    category = FindingCategory(
        regulatory_body_id=acp.id,
        full_path="Operations : Injections",
    )
    db_session.add(category)
    db_session.flush()

    retrieved = db_session.query(FindingCategory).one()
    assert retrieved.full_path == "Operations : Injections"
    assert retrieved.parent == "Operations"
    assert retrieved.child == "Injections"


def test_parent_child_for_complex_paths(db_session, acp):
    """Verify the colon-split correctly handles categories with hyphens
    or other characters that could confuse a naive parser."""
    cases = [
        ("Operations : Injections", "Operations", "Injections"),
        ("Sterile - Personnel : Training & Assessment", "Sterile - Personnel", "Training & Assessment"),
        ("Sterile Compounding Follow-up : Sterile Compounding Follow-up",
         "Sterile Compounding Follow-up", "Sterile Compounding Follow-up"),
    ]
    for full_path, expected_parent, expected_child in cases:
        cat = FindingCategory(regulatory_body_id=acp.id, full_path=full_path)
        assert cat.parent == expected_parent
        assert cat.child == expected_child


def test_category_without_colon_returns_none_parts(db_session, acp):
    """Some malformed input might lack the ' : ' separator."""
    cat = FindingCategory(regulatory_body_id=acp.id, full_path="Just A Name")
    assert cat.parent is None
    assert cat.child is None


def test_duplicate_path_within_body_rejected(db_session, acp):
    db_session.add(FindingCategory(regulatory_body_id=acp.id, full_path="Operations : Injections"))
    db_session.flush()
    db_session.add(FindingCategory(regulatory_body_id=acp.id, full_path="Operations : Injections"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_path_in_different_bodies_allowed(db_session, acp):
    """Different regulators can have categories that happen to have the same name."""
    other = RegulatoryBody(name="BCCP", short_name="BCCP")
    db_session.add(other)
    db_session.flush()

    db_session.add(FindingCategory(regulatory_body_id=acp.id, full_path="Operations : Injections"))
    db_session.add(FindingCategory(regulatory_body_id=other.id, full_path="Operations : Injections"))
    db_session.flush()
    assert db_session.query(FindingCategory).count() == 2


def test_get_or_create_creates_when_missing(db_session, acp):
    assert db_session.query(FindingCategory).count() == 0

    category = get_or_create_category(db_session, acp.id, "Operations : Injections")
    assert category.id is not None
    assert category.full_path == "Operations : Injections"
    assert db_session.query(FindingCategory).count() == 1


def test_get_or_create_returns_existing(db_session, acp):
    """The second call with the same args returns the same row, not a duplicate."""
    first = get_or_create_category(db_session, acp.id, "Operations : Injections")
    second = get_or_create_category(db_session, acp.id, "Operations : Injections")
    assert first.id == second.id
    assert db_session.query(FindingCategory).count() == 1


def test_get_or_create_strips_whitespace(db_session, acp):
    """Whitespace variations should resolve to the same category."""
    a = get_or_create_category(db_session, acp.id, "Operations : Injections")
    b = get_or_create_category(db_session, acp.id, "  Operations : Injections  ")
    assert a.id == b.id
    assert db_session.query(FindingCategory).count() == 1


def test_get_or_create_distinguishes_by_regulatory_body(db_session, acp):
    """Same path under different bodies = different rows."""
    other = RegulatoryBody(name="BCCP", short_name="BCCP")
    db_session.add(other)
    db_session.flush()

    a = get_or_create_category(db_session, acp.id, "Operations : Injections")
    b = get_or_create_category(db_session, other.id, "Operations : Injections")
    assert a.id != b.id
    assert db_session.query(FindingCategory).count() == 2


def test_cannot_delete_regulatory_body_with_categories(db_session, acp):
    db_session.add(FindingCategory(regulatory_body_id=acp.id, full_path="X : Y"))
    db_session.flush()

    db_session.delete(acp)
    with pytest.raises(IntegrityError):
        db_session.flush()

# ================================ API tests ================================
def _setup(client) -> str:
    body = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"}).json()
    return body["id"]


def test_create_category_via_api(client):
    body_id = _setup(client)
    response = client.post(
        "/finding-categories",
        json={"regulatory_body_id": body_id, "full_path": "Operations : Injections"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_path"] == "Operations : Injections"
    assert body["parent"] == "Operations"
    assert body["child"] == "Injections"


def test_create_duplicate_returns_existing_with_200(client):
    body_id = _setup(client)
    payload = {"regulatory_body_id": body_id, "full_path": "Operations : Injections"}
    first = client.post("/finding-categories", json=payload)
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/finding-categories", json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first_id


def test_create_with_unknown_regulator_returns_404(client):
    fake = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/finding-categories",
        json={"regulatory_body_id": fake, "full_path": "X : Y"},
    )
    assert response.status_code == 404


def test_list_categories_filtered_by_body(client):
    body_a = _setup(client)
    body_b = client.post("/regulatory-bodies", json={"name": "BCCP", "short_name": "BCCP"}).json()["id"]

    client.post("/finding-categories", json={"regulatory_body_id": body_a, "full_path": "A : 1"})
    client.post("/finding-categories", json={"regulatory_body_id": body_a, "full_path": "A : 2"})
    client.post("/finding-categories", json={"regulatory_body_id": body_b, "full_path": "B : 1"})

    all_cats = client.get("/finding-categories").json()
    assert len(all_cats) == 3

    body_a_only = client.get(f"/finding-categories?regulatory_body_id={body_a}").json()
    assert len(body_a_only) == 2


def test_parent_and_child_appear_in_api_response(client):
    """Verify the computed properties surface through the API."""
    body_id = _setup(client)
    response = client.post(
        "/finding-categories",
        json={"regulatory_body_id": body_id, "full_path": "Sterile - Personnel : Training & Assessment"},
    )
    body = response.json()
    assert body["parent"] == "Sterile - Personnel"
    assert body["child"] == "Training & Assessment"


def test_whitespace_normalization_via_api(client):
    """Categories with extra whitespace resolve to the same row."""
    body_id = _setup(client)
    a = client.post(
        "/finding-categories",
        json={"regulatory_body_id": body_id, "full_path": "Operations : Injections"},
    )
    b = client.post(
        "/finding-categories",
        json={"regulatory_body_id": body_id, "full_path": "  Operations : Injections  "},
    )
    assert b.status_code == 200  # existed
    assert a.json()["id"] == b.json()["id"]