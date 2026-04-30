import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.base import Base


@pytest.fixture(scope="session")
def test_engine():
    """One engine for the whole test session. Creates and drops all tables."""
    engine = create_engine(settings.test_database_url, future=True)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(test_engine):
    """Each test runs in its own transaction that's rolled back at the end.

    This is fast and gives every test a clean database without recreating
    tables between tests.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    # join_transaction_mode="create_savepoint" means the session works against a
    # savepoint, so session.rollback() only rolls back to the savepoint and leaves
    # the outer transaction alive for the final transaction.rollback() below.
    TestSession = sessionmaker(
        bind=connection, future=True, join_transaction_mode="create_savepoint"
    )
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """A FastAPI test client whose endpoints share `db_session`."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()