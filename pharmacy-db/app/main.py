from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers import (
    finding_categories,
    findings,
    assessments, 
    regulatory_bodies, 
    pharmacies, 
    inspectors, 
    documents, 
    cases,           
)


app = FastAPI(title="Pharmacy Inspection DB", version="0.1.0")
app.include_router(regulatory_bodies.router)
app.include_router(pharmacies.router)
app.include_router(inspectors.router)
app.include_router(documents.router)
app.include_router(cases.router)
app.include_router(assessments.router)
app.include_router(finding_categories.router)
app.include_router(findings.router)

@app.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    """Returns OK if the app is running and the database is reachable."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}

