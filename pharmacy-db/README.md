# Pharmacy Inspection Database

Stores parsed pharmacy inspection case summaries (currently from the Alberta
College of Pharmacy). Receives JSON from the case-summary extractor and
exposes the data via a FastAPI HTTP API.

## Stack
- PostgreSQL 16 (with pgvector extension available, unused for now)
- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- Docker + docker-compose for local development

## Running locally

    cp .env.example .env
    docker compose up -d --build
    docker compose exec app alembic upgrade head
    docker compose exec app pytest

The API is at http://localhost:8000 and docs at http://localhost:8000/docs.

## Project layout

    app/
        models/       SQLAlchemy ORM models, one file per entity
        schemas/      Pydantic request/response schemas
        routers/      FastAPI routers, one per resource
        services/     Business logic (kept separate from HTTP layer)
    alembic/          Database migrations
    tests/            pytest tests