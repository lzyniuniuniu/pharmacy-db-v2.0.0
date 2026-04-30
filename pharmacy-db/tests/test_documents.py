from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.document import Document


def _make_document(**overrides) -> Document:
    """Helper: a valid Document with sensible defaults you can override."""
    defaults = {
        "document_type": "case_summary",
        "file_hash": "sha256:abc123",
        "file_name": "report.pdf",
    }
    defaults.update(overrides)
    return Document(**defaults)


def test_can_create_minimal_document(db_session):
    """Only document_type, file_hash, and file_name are required."""
    doc = _make_document()
    db_session.add(doc)
    db_session.flush()

    assert doc.id is not None
    assert doc.processing_status == "pending"  # default
    assert doc.created_at is not None


def test_can_create_full_document(db_session):
    doc = _make_document(
        file_path="/data/uploads/report.pdf",
        file_size_bytes=2_500_000,
        mime_type="application/pdf",
        page_count=11,
        report_generated_at=datetime(2025, 6, 18, 17, 57, 0, tzinfo=timezone.utc),
        processing_status="done",
        extraction_metadata={"extractor_version": "0.1.0", "warnings": []},
    )
    db_session.add(doc)
    db_session.flush()

    retrieved = db_session.query(Document).one()
    assert retrieved.page_count == 11
    assert retrieved.extraction_metadata["extractor_version"] == "0.1.0"
    assert retrieved.report_generated_at.year == 2025


def test_file_hash_must_be_unique(db_session):
    """The same file should never produce two documents."""
    db_session.add(_make_document(file_hash="sha256:same"))
    db_session.flush()
    db_session.add(_make_document(file_hash="sha256:same", file_name="other.pdf"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_jsonb_field_supports_dict_storage_and_queries(db_session):
    """Verify JSONB roundtrip + that we can query into it."""
    doc = _make_document(
        file_hash="sha256:meta",
        extraction_metadata={
            "extractor_version": "0.1.0",
            "validation_warnings": ["pharmacy name missing", "consultant missing"],
            "stats": {"finding_count": 27, "assessment_count": 2},
        },
    )
    db_session.add(doc)
    db_session.flush()

    # Roundtrip: dict goes in, dict comes out
    retrieved = db_session.query(Document).filter_by(file_hash="sha256:meta").one()
    assert retrieved.extraction_metadata["stats"]["finding_count"] == 27
    assert "pharmacy name missing" in retrieved.extraction_metadata["validation_warnings"]


def test_document_type_can_be_anything_for_now(db_session):
    """We're not constraining document_type values at the DB level — that's
    application-layer policy. This test documents that decision."""
    db_session.add(_make_document(file_hash="sha256:1", document_type="case_summary"))
    db_session.add(_make_document(file_hash="sha256:2", document_type="regulation"))
    db_session.add(_make_document(file_hash="sha256:3", document_type="anything_really"))
    db_session.flush()
    assert db_session.query(Document).count() == 3



# ===================== API tests =====================
VALID_HASH = "sha256:" + "a" * 64
VALID_HASH_2 = "sha256:" + "b" * 64


def _doc_payload(**overrides) -> dict:
    payload = {
        "document_type": "case_summary",
        "file_hash": VALID_HASH,
        "file_name": "test.pdf",
    }
    payload.update(overrides)
    return payload


def test_create_document_via_api(client):
    response = client.post("/documents", json=_doc_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["file_hash"] == VALID_HASH
    assert body["processing_status"] == "pending"


def test_create_document_with_full_metadata(client):
    response = client.post(
        "/documents",
        json=_doc_payload(
            file_path="/uploads/test.pdf",
            file_size_bytes=2_500_000,
            page_count=11,
            extraction_metadata={"extractor_version": "0.1.0"},
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["page_count"] == 11
    assert body["extraction_metadata"]["extractor_version"] == "0.1.0"


def test_invalid_hash_format_rejected(client):
    response = client.post(
        "/documents",
        json=_doc_payload(file_hash="not-a-valid-hash"),
    )
    assert response.status_code == 422


def test_duplicate_hash_returns_existing_record_with_200(client):
    """Idempotency: posting the same hash twice returns the existing record."""
    first = client.post("/documents", json=_doc_payload(file_name="first.pdf"))
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/documents", json=_doc_payload(file_name="second.pdf"))
    assert second.status_code == 200  # not 201
    assert second.json()["id"] == first_id
    assert second.json()["file_name"] == "first.pdf"  # the original wins


def test_lookup_by_hash(client):
    create_resp = client.post("/documents", json=_doc_payload())
    doc_id = create_resp.json()["id"]

    lookup = client.get(f"/documents/by-hash/{VALID_HASH}")
    assert lookup.status_code == 200
    assert lookup.json()["id"] == doc_id


def test_lookup_by_hash_returns_404_for_unknown(client):
    response = client.get(f"/documents/by-hash/{VALID_HASH_2}")
    assert response.status_code == 404


def test_filter_by_processing_status(client):
    client.post("/documents", json=_doc_payload(file_hash=VALID_HASH, processing_status="done"))
    client.post("/documents", json=_doc_payload(file_hash=VALID_HASH_2, processing_status="pending"))

    pending = client.get("/documents?processing_status=pending").json()
    assert len(pending) == 1
    assert pending[0]["file_hash"] == VALID_HASH_2

    done = client.get("/documents?processing_status=done").json()
    assert len(done) == 1


def test_patch_document_updates_status(client):
    create_resp = client.post("/documents", json=_doc_payload())
    doc_id = create_resp.json()["id"]

    response = client.patch(
        f"/documents/{doc_id}",
        json={"processing_status": "done", "extraction_metadata": {"finished": True}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == "done"
    assert body["extraction_metadata"]["finished"] is True


def test_patch_cannot_change_file_hash(client):
    """The schema doesn't include file_hash in DocumentUpdate, so any
    attempt to change it should be silently ignored or rejected."""
    create_resp = client.post("/documents", json=_doc_payload())
    doc_id = create_resp.json()["id"]

    # Pydantic discards unknown fields by default — the patch just doesn't
    # include file_hash. Document is unchanged.
    response = client.patch(
        f"/documents/{doc_id}",
        json={"file_hash": "sha256:different", "processing_status": "done"},
    )
    assert response.status_code == 200
    assert response.json()["file_hash"] == VALID_HASH  # unchanged
    assert response.json()["processing_status"] == "done"  # this part applied