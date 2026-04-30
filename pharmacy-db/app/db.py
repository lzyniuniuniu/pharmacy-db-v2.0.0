from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


# Create a connection pool to the PostgreSQL database using the URL from settings.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

# Create a session factory. autoflush and autocommit mean changes are only sent to DB
# when we explicitly call commit(), and future=True enables SQLAlchemy 2.0 style usage.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()