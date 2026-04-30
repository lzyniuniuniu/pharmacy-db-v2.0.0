from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.assessment import Assessment
from app.models.case import Case
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


def test_can_create_assessment(db_session, case_pp0002449):
    assessment = Assessment(
        case_id=case_pp0002449.id,
        ordinal=1,
        assessment_date=date(2025, 3, 19),
    )
    db_session.add(assessment)
    db_session.flush()

    retrieved = db_session.query(Assessment).filter_by(case_id=case_pp0002449.id).one()
    assert retrieved.ordinal == 1
    assert retrieved.assessment_date == date(2025, 3, 19)
    assert retrieved.case.case_number == "PP0002449"


def test_assessment_can_have_null_date(db_session, case_pp0002449):
    """The extractor produces an 'unknown' assessment when no date parses."""
    assessment = Assessment(case_id=case_pp0002449.id, ordinal=99, assessment_date=None)
    db_session.add(assessment)
    db_session.flush()
    assert assessment.id is not None


def test_case_can_have_multiple_assessments(db_session, case_pp0002449):
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=1, assessment_date=date(2025, 3, 19)))
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=2, assessment_date=date(2025, 4, 30)))
    db_session.flush()

    assessments = (
        db_session.query(Assessment)
        .filter_by(case_id=case_pp0002449.id)
        .order_by(Assessment.ordinal)
        .all()
    )
    assert len(assessments) == 2
    assert assessments[0].ordinal == 1
    assert assessments[1].ordinal == 2


def test_duplicate_ordinal_within_case_rejected(db_session, case_pp0002449):
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=1, assessment_date=date(2025, 3, 19)))
    db_session.flush()
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=1, assessment_date=date(2025, 4, 30)))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_ordinal_in_different_cases_allowed(db_session, acp):
    case_a = Case(regulatory_body_id=acp.id, case_number="PP01")
    case_b = Case(regulatory_body_id=acp.id, case_number="PP02")
    db_session.add(case_a)
    db_session.add(case_b)
    db_session.flush()

    db_session.add(Assessment(case_id=case_a.id, ordinal=1))
    db_session.add(Assessment(case_id=case_b.id, ordinal=1))
    db_session.flush()
    assert db_session.query(Assessment).count() == 2


def test_deleting_case_cascades_to_assessments(db_session, case_pp0002449):
    """Critical behavior: deleting a case removes its assessments."""
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=1))
    db_session.add(Assessment(case_id=case_pp0002449.id, ordinal=2))
    db_session.flush()
    assert db_session.query(Assessment).count() == 2

    db_session.delete(case_pp0002449)
    db_session.flush()
    assert db_session.query(Assessment).count() == 0


def test_case_id_required(db_session):
    """An assessment can't exist without a case."""
    assessment = Assessment(ordinal=1)  # no case_id
    db_session.add(assessment)
    with pytest.raises(IntegrityError):
        db_session.flush()


# ====================== Api tests ======================
def _setup(client) -> dict[str, str]:
    """Create ACP + a case via the API. Returns the ids."""
    body = client.post("/regulatory-bodies", json={"name": "ACP", "short_name": "ACP"}).json()
    case = client.post("/cases", json={
        "case_number": "PP0002449", "regulatory_body_id": body["id"],
    }).json()
    return {"body_id": body["id"], "case_id": case["id"]}


def test_create_assessment_via_api(client):
    ids = _setup(client)
    response = client.post(
        "/assessments",
        json={"case_id": ids["case_id"], "ordinal": 1, "assessment_date": "2025-03-19"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ordinal"] == 1
    assert body["assessment_date"] == "2025-03-19"
    assert body["case_id"] == ids["case_id"]


def test_create_assessment_with_null_date(client):
    ids = _setup(client)
    response = client.post(
        "/assessments",
        json={"case_id": ids["case_id"], "ordinal": 99, "assessment_date": None},
    )
    assert response.status_code == 201
    assert response.json()["assessment_date"] is None


def test_create_assessment_with_unknown_case_returns_404(client):
    fake = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/assessments",
        json={"case_id": fake, "ordinal": 1, "assessment_date": "2025-03-19"},
    )
    assert response.status_code == 404


def test_duplicate_ordinal_returns_409(client):
    ids = _setup(client)
    payload = {"case_id": ids["case_id"], "ordinal": 1, "assessment_date": "2025-03-19"}
    client.post("/assessments", json=payload)
    response = client.post("/assessments", json=payload)
    assert response.status_code == 409


def test_list_assessments_filtered_by_case(client):
    ids = _setup(client)
    other_case = client.post("/cases", json={
        "case_number": "PP0002582", "regulatory_body_id": ids["body_id"],
    }).json()

    client.post("/assessments", json={"case_id": ids["case_id"], "ordinal": 1, "assessment_date": "2025-03-19"})
    client.post("/assessments", json={"case_id": ids["case_id"], "ordinal": 2, "assessment_date": "2025-04-30"})
    client.post("/assessments", json={"case_id": other_case["id"], "ordinal": 1, "assessment_date": "2025-03-28"})

    all_assessments = client.get("/assessments").json()
    assert len(all_assessments) == 3

    by_case = client.get(f"/assessments?case_id={ids['case_id']}").json()
    assert len(by_case) == 2
    assert by_case[0]["ordinal"] == 1
    assert by_case[1]["ordinal"] == 2


def test_patch_assessment_corrects_date(client):
    """A common workflow: extractor failed to parse a date; user corrects it."""
    ids = _setup(client)
    create = client.post("/assessments", json={
        "case_id": ids["case_id"], "ordinal": 1, "assessment_date": None,
    })
    assessment_id = create.json()["id"]

    response = client.patch(
        f"/assessments/{assessment_id}",
        json={"assessment_date": "2025-03-19"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment_date"] == "2025-03-19"
    assert body["ordinal"] == 1  # unchanged


def test_patch_cannot_change_ordinal_or_case(client):
    """The schema doesn't expose ordinal or case_id for update — extra
    fields in the payload are silently dropped."""
    ids = _setup(client)
    create = client.post("/assessments", json={
        "case_id": ids["case_id"], "ordinal": 1, "assessment_date": "2025-03-19",
    })
    assessment_id = create.json()["id"]

    other_case = client.post("/cases", json={
        "case_number": "PP02", "regulatory_body_id": ids["body_id"],
    }).json()

    response = client.patch(
        f"/assessments/{assessment_id}",
        json={
            "ordinal": 99,
            "case_id": other_case["id"],
            "assessment_date": "2025-04-30",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ordinal"] == 1  # not changed
    assert body["case_id"] == ids["case_id"]  # not changed
    assert body["assessment_date"] == "2025-04-30"  # this part applied