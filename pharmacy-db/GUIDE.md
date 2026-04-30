# Learner's Guide — pharmacy-db

This guide explains the project for someone new to FastAPI, SQLAlchemy, and
relational databases. It covers:

1. [Big picture — what this project is](#1-big-picture)
2. [How a request travels through the code](#2-how-a-request-travels)
3. [The data model — all 8 tables and how they relate](#3-the-data-model)
4. [Module-by-module breakdown](#4-module-by-module-breakdown)
5. [How the layers talk to each other](#5-how-the-layers-talk-to-each-other)
6. [Database migrations with Alembic](#6-database-migrations-with-alembic)
7. [Testing strategy](#7-testing-strategy)
8. [Docker and docker-compose](#8-docker-and-docker-compose)
9. [Common workflows / cheat sheet](#9-common-workflows--cheat-sheet)
10. [Connecting to the database](#10-connecting-to-the-database)
11. [Glossary](#11-glossary)

---

## 1. Big picture

This project is a **REST API** that stores pharmacy inspection data. The data
arrives as PDF case summaries from the Alberta College of Pharmacy (and later
other regulators). A separate "extractor" service reads those PDFs and POSTs
the structured data here, where it is stored in PostgreSQL and made available
via HTTP endpoints.

| Layer | Tool |
|---|---|
| HTTP API | **FastAPI** |
| ORM (Python ↔ SQL bridge) | **SQLAlchemy 2.0** |
| Database | **PostgreSQL 16** |
| Schema migrations | **Alembic** |
| Validation | **Pydantic v2** |
| Testing | **Pytest** |
| Containers | **Docker + docker-compose** |

A useful analogy:

- **Routers** = the front-of-house staff who take orders
- **Schemas (Pydantic)** = the order pad that checks the order is correct
- **Models (SQLAlchemy)** = the kitchen that knows what every dish is made of
- **Database** = the pantry where everything is stored
- **Alembic migrations** = the person who rearranges the pantry shelves whenever the menu changes

---

## 2. How a request travels

Walking through `POST /pharmacies` from start to finish:

```
Client (curl, Postman, another service)
   │  POST /pharmacies
   │  body: { "regulatory_body_id": "...", "name": "...", "license_number": "..." }
   ▼
app/main.py            ← creates the FastAPI app, wires in routers
   │
   ▼
app/routers/pharmacies.py     create_pharmacy()
   │
   ├─► app/schemas/pharmacy.py
   │       PharmacyCreate validates the JSON.
   │       Missing/invalid fields → automatic 422 response.
   │
   ├─► app/db.py (get_db dependency)
   │       Opens a Session, gives it to the route, closes it after.
   │
   ├─► app/models/pharmacy.py
   │       A Pharmacy() Python object is built from the validated payload.
   │       db.add() stages it; db.commit() writes it to PostgreSQL.
   │       PostgreSQL fills in defaults (id from server-side, timestamps).
   │
   └─► app/schemas/pharmacy.py
           PharmacyRead serialises the saved row back into JSON.
   │
   ▼
HTTP 201 Created
{ "id": "...", "regulatory_body_id": "...", "name": "...", "created_at": "..." }
```

The same pattern applies to every resource (`/regulatory-bodies`,
`/inspectors`, `/cases`, `/documents`, `/assessments`,
`/finding-categories`).

---

## 3. The data model

There are **8 tables**. Some hold reference data (the "who" and "where"),
some hold workflow data (the "what"), and one holds raw files.

### Table inventory at a glance

| # | Table | Purpose | Lives where |
|---|---|---|---|
| 1 | `regulatory_bodies` | A regulator (e.g., Alberta College of Pharmacy) | reference |
| 2 | `pharmacies` | A licensed pharmacy under a regulator | reference |
| 3 | `inspectors` | A consultant/inspector employed by a regulator | reference |
| 4 | `finding_categories` | Controlled vocabulary for findings, scoped per regulator | reference |
| 5 | `documents` | An ingested PDF (or other source file) | content |
| 6 | `cases` | The regulatory file kept on a pharmacy | workflow |
| 7 | `assessments` | One visit/assessment within a case | workflow |
| 8 | `findings` | Individual findings recorded during an assessment | workflow |

> All 8 tables are implemented. `findings` joins `assessments` to
> `finding_categories` and includes Postgres full-text search on the
> verbatim description (a generated `tsvector` column with a GIN index).

### The relationship diagram

The most important picture in this project. Read each arrow as
**"belongs to"** — pointing from the *child* (the row that holds the foreign
key) to the *parent* (the row being referenced).

```
                    ┌────────────────────────┐
                    │   regulatory_bodies    │  ← The "tenant" of the system.
                    │  id, name, short_name  │    Everything is scoped to one regulator.
                    │  jurisdiction          │
                    └──────┬──┬──┬──┬────────┘
                           │  │  │  │
            ┌──────────────┘  │  │  └──────────────────┐
            │                 │  │                     │
            ▼                 ▼  ▼                     ▼
   ┌────────────────┐  ┌────────────────┐   ┌────────────────────┐
   │   pharmacies   │  │   inspectors   │   │ finding_categories │
   │ id             │  │ id             │   │ id                 │
   │ regulatory_    │  │ regulatory_    │   │ regulatory_body_id │
   │   body_id (FK) │  │   body_id (FK) │   │ full_path          │
   │ name           │  │ full_name      │   │   "Operations :    │
   │ license_number │  │ email          │   │    Injections"     │
   └────────┬───────┘  │ role           │   └────────────────────┘
            │          └────────┬───────┘
            │                   │
            │     ┌─────────────┘
            │     │
            ▼     ▼
       ┌──────────────────────────────┐
       │           cases              │  ← The central workflow record.
       │ id                           │     One per (regulator, case_number).
       │ regulatory_body_id  (FK)     │
       │ pharmacy_id         (FK,nul) │     "nul" = nullable; data may arrive
       │ consultant_id       (FK,nul) │      before pharmacy/consultant is known.
       │ case_number                  │
       │ case_type, case_state, ...   │
       └──────┬─────────────────┬─────┘
              │                 │
              │                 └─────────────────┐
              ▼                                   ▼
      ┌────────────────┐              ┌─────────────────────────┐
      │  assessments   │              │       documents         │
      │ id             │              │ id                      │
      │ case_id (FK)   │              │ case_id (FK, SET NULL)  │
      │ ordinal        │              │ file_hash (UNIQUE)      │
      │ assessment_    │              │ file_name, file_path    │
      │   date         │              │ processing_status       │
      └────────────────┘              └─────────────────────────┘
        (CASCADE)                       (SET NULL — see below)
```

### What the foreign keys mean

| Foreign key | Read it as | On delete behaviour |
|---|---|---|
| `pharmacies.regulatory_body_id` | a pharmacy belongs to one regulator | RESTRICT — can't delete a regulator that still has pharmacies |
| `inspectors.regulatory_body_id` | an inspector works for one regulator | RESTRICT |
| `finding_categories.regulatory_body_id` | each regulator has its own vocabulary | RESTRICT |
| `cases.regulatory_body_id` | a case is filed by one regulator | RESTRICT |
| `cases.pharmacy_id` | a case is about one pharmacy (eventually) | RESTRICT — can't delete a pharmacy with open cases |
| `cases.consultant_id` | a case may be assigned to one inspector | RESTRICT |
| `assessments.case_id` | an assessment belongs to one case | CASCADE — delete the case, its assessments go with it |
| `documents.case_id` | a document may be linked to one case | SET NULL — delete the case, the file record survives but unlinks |
| `findings.assessment_id` | a finding belongs to one assessment | CASCADE — delete the assessment, its findings go with it |
| `findings.case_id` | denormalized link to the case for query convenience | CASCADE |
| `findings.category_id` | optional link into the regulator's vocabulary | RESTRICT — can't delete a category still used by findings |
| `findings.source_document_id` | optional link to the PDF this finding came from | SET NULL — delete the document, the finding survives unlinked |

### Why the three different ON DELETE rules?

Pick the one that matches the real-world meaning:

- **RESTRICT** — "you can't throw this out while things still depend on it." Used
  for reference data (regulators, pharmacies, inspectors). If you tried to delete
  a pharmacy that still has open cases, that would be a data-integrity bug.
- **CASCADE** — "this thing cannot exist without its parent." An assessment is
  meaningless without its case, so deleting the case removes them too.
- **SET NULL** — "the parent can disappear, but I'm still useful on my own."
  A PDF file remains evidence even if the case it described is later removed
  from the system; we just lose the link.

### Uniqueness constraints (composite)

Many tables are unique *within* a regulator, not globally. This matters because
two regulators could coincidentally use the same case number or license number.

| Table | Unique on | Why |
|---|---|---|
| `regulatory_bodies` | `name`, `short_name` (each unique) | regulators are globally unique |
| `pharmacies` | `(regulatory_body_id, license_number)` | license numbers repeat across provinces |
| `inspectors` | `(regulatory_body_id, email)` | an email could in theory exist twice |
| `cases` | `(regulatory_body_id, case_number)` | case numbers repeat across regulators |
| `assessments` | `(case_id, ordinal)` | "first assessment" must be unique within a case |
| `finding_categories` | `(regulatory_body_id, full_path)` | each regulator has its own taxonomy |
| `documents` | `file_hash` (globally unique) | the same file is the same file regardless of regulator |
| `findings` | `(assessment_id, ordinal)` | "finding #1" must be unique within an assessment |

### Reading the diagram in plain English

> The system tracks **regulatory bodies**. Each regulator licenses **pharmacies**
> and employs **inspectors** (consultants). Each regulator also has its own
> taxonomy of **finding categories**.
>
> When something happens with a pharmacy, the regulator opens a **case**
> (identified by the regulator's `case_number`). A case usually points to one
> pharmacy and one consultant, but those fields are nullable because the data
> sometimes arrives before we know who is involved.
>
> Within a case there can be one or more **assessments** (visits or evaluations).
>
> Separately, **documents** (PDFs) are ingested. A document has a unique file
> hash so the same PDF is never stored twice. A document is optionally linked to
> a case — when a PDF is parsed, we link it once we know which case it
> describes.

### A worked example

Imagine: ACP visits "Mint Health + Drugs: Beaverlodge" on 2026-04-15. The visit
turns up two issues — both in the "Operations : Injections" category. They send
us a PDF afterwards.

The data ends up like this:

```
regulatory_bodies
   └─ ACP

pharmacies
   └─ Mint Health + Drugs: Beaverlodge   (regulatory_body_id → ACP)

inspectors
   └─ Tyler Watson                        (regulatory_body_id → ACP)

finding_categories
   └─ "Operations : Injections"           (regulatory_body_id → ACP)

cases
   └─ PP0002449                           (regulatory_body_id → ACP,
                                           pharmacy_id → Mint Beaverlodge,
                                           consultant_id → Tyler)

assessments
   └─ ordinal=1, assessment_date=2026-04-15  (case_id → PP0002449)

documents
   └─ file_hash=sha256:..., file_name=PP0002449.pdf
                                            (case_id → PP0002449)

findings
   ├─ assessment_id → assessment 1, category_id → "Operations : Injections",
   │   ordinal=1, description_verbatim="Review anaphylaxis kit ..."
   └─ assessment_id → assessment 1, category_id → "Operations : Injections",
       ordinal=2, description_verbatim="Update epinephrine dosing log ..."
```

### What makes `findings` a little special

On top of the usual columns, `findings` uses three Postgres features:

- **JSONB** for `referenced_standards` — a list of objects like
  `{"raw_text": "...", "standard_code": "6.5", "document": "SOLP"}`.
- **ARRAY columns** for `referenced_urls` (text[]),
  `source_page_numbers` (int[]), and `summary_bullets` (text[]).
- **Generated `tsvector` + GIN index** on `description_verbatim` so
  `/findings?search=narcotic` is fast and supports stemming
  (`medications` matches `medication`).

---

## 4. Module-by-module breakdown

### `pyproject.toml`

The single source of truth for project dependencies and tool config. Lists
runtime packages (`fastapi`, `sqlalchemy`, `psycopg`, `alembic`, `pydantic`),
dev packages (`pytest`, `httpx`, `ruff`), and tool settings (Pytest test path,
Ruff line length).

### `app/config.py`

Loads configuration from environment variables / `.env` via Pydantic Settings.

```python
class Settings(BaseSettings):
    database_url: str
    test_database_url: str
    log_level: str = "INFO"
    environment: str = "development"
```

The `settings = Settings()` at the bottom creates a single shared instance —
every other module just does `from app.config import settings`. If
`database_url` or `test_database_url` are missing the app fails fast at startup.

### `app/db.py`

The connection layer.

- **`engine`** — a connection pool to PostgreSQL (`pool_pre_ping=True` revives
  stale connections automatically).
- **`SessionLocal`** — a factory that produces `Session` objects. A session is
  a unit of work — you stage changes with `db.add()`, then `db.commit()` to
  persist them or `db.rollback()` to discard them.
- **`get_db()`** — a FastAPI dependency that yields a session and closes it in
  `finally`. Used everywhere as `db: Session = Depends(get_db)`.

### `app/main.py`

Creates the FastAPI `app` object, defines `/health`, and registers every
router with `app.include_router(...)`. Adding a new resource means adding it to
this list.

### `app/models/base.py`

Three reusable building blocks:

- **`Base`** — every ORM model must subclass this so SQLAlchemy tracks it.
- **`UUIDMixin`** — adds `id: UUID` (auto-generated by `uuid4()` in Python).
- **`TimestampMixin`** — adds `created_at` and `updated_at`, both filled and
  refreshed by the database itself.

Every model in the project inherits all three, e.g.:
```python
class Pharmacy(Base, UUIDMixin, TimestampMixin):
    ...
```

### Resource modules

For each resource there are usually four files:

| File | Role | Example |
|---|---|---|
| `app/models/<name>.py` | SQLAlchemy ORM model — maps Python class to a SQL table | `pharmacy.py` |
| `app/schemas/<name>.py` | Pydantic schemas — define JSON shape in/out | `pharmacy.py` |
| `app/routers/<name>.py` | FastAPI router — defines URLs and HTTP methods | `pharmacies.py` |
| `tests/test_<name>.py` | Pytest tests | `test_pharmacies.py` |

Schemas are usually split into `XxxCreate`, `XxxUpdate`, and `XxxRead` so the
client cannot set server-controlled fields like `id`, `created_at`,
`updated_at` on creation, and so partial updates (`PATCH`) are possible without
forcing every field.

### `alembic/env.py`

Configures Alembic:
- pulls the database URL from `settings`
- imports every model module so Alembic's `autogenerate` can compare your model
  classes against the live database schema

When you add a new model file, **import it here** or autogenerate won't notice
the new table.

### `tests/conftest.py`

Three fixtures, all ultimately backed by the `test_database_url`:

| Fixture | Scope | What it does |
|---|---|---|
| `test_engine` | session | creates all tables once, drops them at the end |
| `db_session` | function | each test runs inside its own transaction, rolled back at the end (clean DB per test) |
| `client` | function | a FastAPI `TestClient` whose `get_db` dependency is overridden to return the test's `db_session` |

`join_transaction_mode="create_savepoint"` lets the session do its own internal
rollbacks (useful when a test triggers an `IntegrityError`) without disturbing
the outer test transaction.

---

## 5. How the layers talk to each other

```
┌──────────────────────────────────────────────────────────┐
│                       HTTP Client                        |
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  app/main.py — FastAPI app, registers all routers        │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  app/routers/<resource>.py                               │
│  • path + HTTP method                                    │
│  • status codes, error handling                          │
│  • Depends(get_db) → injects a Session                   │
└────────┬───────────────────────────────────┬─────────────┘
         │                                   │
         ▼ validates / shapes data            ▼ persists / queries
┌────────────────────────┐         ┌──────────────────────────┐
│  app/schemas/          │         │  app/models/             │
│  Pydantic              │         │  SQLAlchemy ORM          │
│  XxxCreate / XxxRead   │         │  maps class ↔ table      │
└────────────────────────┘         └──────────────┬───────────┘
                                                  │
                                                  ▼
                                  ┌──────────────────────────┐
                                  │  app/db.py               │
                                  │  engine + SessionLocal   │
                                  │  get_db()                │
                                  └──────────────┬───────────┘
                                                 │ SQL
                                                 ▼
                                  ┌──────────────────────────┐
                                  │       PostgreSQL         │
                                  │   8 tables + FKs         │
                                  └──────────────────────────┘
```

`app/config.py` feeds `settings.database_url` into both `app/db.py` (runtime)
and `alembic/env.py` (migrations). Same database URL, two consumers.

---

## 6. Database migrations with Alembic

A **migration** is a Python script that changes the database schema (creates a
table, adds a column, alters a constraint, etc.). Alembic stores them in
`alembic/versions/`.

### Day-to-day workflow

```bash
# 1. Edit a model file (or create a new one)
# 2. Generate a migration that captures the diff
docker compose exec app alembic revision --autogenerate -m "describe change"

# 3. Review the generated file in alembic/versions/.
#    Autogenerate is helpful but not always perfect — read both
#    upgrade() and downgrade() to make sure they make sense.

# 4. Apply it
docker compose exec app alembic upgrade head

# 5. Roll back one step (if needed)
docker compose exec app alembic downgrade -1
```

### Important rule — `downgrade()` must reverse `upgrade()`

If `upgrade()` drops an index, `downgrade()` must create it. If `upgrade()`
doesn't drop an index, `downgrade()` must not create it. Mismatches lead to
"relation already exists" or "relation does not exist" errors when you roll
back.

### The `regulatory_body` import in `env.py`

For autogenerate to detect a new table, the model class must be imported by
`alembic/env.py`. Add a line for each new model:

```python
from app.models import (  # noqa: F401
    regulatory_body,
    pharmacy,
    inspector,
    document,
    case,
    assessment,
    finding_category,
    finding,
```

---

## 7. Testing strategy

The test database is separate from the dev database (`pharmacy_test` vs
`pharmacy_db` in `.env`). Tables are created once before all tests and dropped
once at the end — fast.

Each test runs inside a transaction that is rolled back at the end. That means:

- No test data leaks between tests
- Tests run in any order
- You can freely insert, delete, even trigger `IntegrityError` in one test —
  the next test starts empty

### Two flavours of tests

| What you test | Use this fixture |
|---|---|
| ORM, models, constraints, relationships | `db_session` |
| HTTP routes (status codes, request/response JSON) | `client` |

The `client` internally uses `db_session`, so a route handler and a direct DB
check inside the same test see exactly the same data.

### Common SQLAlchemy gotcha — caches

After SQL like `ON DELETE SET NULL` runs in PostgreSQL, your in-memory Python
objects still have the old values. Call `db_session.expire_all()` to force a
re-read from the DB. (See `test_deleting_case_orphans_documents_not_deletes_them`.)

---

## 8. Docker and docker-compose

Two services:

| Service | Image | Role |
|---|---|---|
| `db` | `pgvector/pgvector:pg16` | PostgreSQL with pgvector pre-installed |
| `app` | `Dockerfile` (Python 3.12) | Uvicorn running the FastAPI app |

Networking inside Compose:

- The `app` container reaches the DB at hostname **`db`** (the service name) on
  port **5432** — that's why `DATABASE_URL` looks like
  `postgresql+psycopg://...@db:5432/...`.
- Your **Mac** reaches the DB at `localhost:5433` (mapped because port 5432 was
  already taken by a local Postgres).

---

## 9. Common workflows / cheat sheet

### Reading the routes from a router file → writing a curl

For an endpoint like:

```python
router = APIRouter(prefix="/pharmacies")

@router.get("/{pharmacy_id}", response_model=PharmacyRead)
def get_pharmacy(pharmacy_id: UUID, db: Session = Depends(get_db)):
    ...
```

The mapping is:

| Code | curl part |
|---|---|
| `prefix + path` | URL: `http://localhost:8000/pharmacies/<id>` |
| `@router.get` | method: GET (default, no `-X` needed) |
| `payload: SomeSchema` parameter | `-H "Content-Type: application/json" -d '{...}'` |
| `Query(...)` parameter | `?key=value` on the URL |

Examples:

```bash
# List all
curl http://localhost:8000/regulatory-bodies | python3 -m json.tool

# Filter list
curl "http://localhost:8000/pharmacies?regulatory_body_id=<UUID>"

# Create
curl -X POST http://localhost:8000/regulatory-bodies \
  -H "Content-Type: application/json" \
  -d '{"name":"Alberta College of Pharmacy","short_name":"ACP"}'

# Get one
curl http://localhost:8000/pharmacies/<UUID>

# Partial update
curl -X PATCH http://localhost:8000/pharmacies/<UUID> \
  -H "Content-Type: application/json" \
  -d '{"name":"New name"}'
```

### Spinning everything up

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose exec app pytest -v
```

### Adding a new resource (the standard recipe)

1. Create `app/models/<thing>.py` (subclass `Base, UUIDMixin, TimestampMixin`).
2. Add the import to `alembic/env.py`.
3. Generate a migration: `alembic revision --autogenerate -m "create things"`.
4. Review the migration; remove any unwanted autogenerate noise (e.g. unrelated
   `drop_index` calls).
5. Apply it: `alembic upgrade head`.
6. Create `app/schemas/<thing>.py` — `XxxCreate`, `XxxUpdate`, `XxxRead`.
7. Create `app/routers/<things>.py` — list, create, get-by-id, patch.
8. Register the router in `app/main.py`.
9. Write `tests/test_<things>.py` covering both ORM-level invariants and the
   HTTP API.

---

## 10. Connecting to the database

Sometimes you just want to poke around the live tables — list them, peek at
rows, run an ad-hoc `SELECT`. There are three good ways.

### A. `psql` inside the `db` container (easiest, no local install needed)

```bash
# Open an interactive psql shell
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# Or, if you don't have those env vars exported in your shell, use the
# values from .env directly:
docker compose exec db psql -U pharmacy -d pharmacy_db
```

Once inside `psql`, useful meta-commands:

| Command | What it shows |
|---|---|
| `\dt` | list all tables |
| `\d findings` | columns, types, indexes, FKs of the `findings` table |
| `\di` | list all indexes |
| `\dn` | list schemas |
| `\du` | list roles/users |
| `\l` | list databases |
| `\x` | toggle expanded (one-column-per-line) output |
| `\q` | quit |

A quick smoke-test session:

```sql
\dt
SELECT count(*) FROM regulatory_bodies;
SELECT case_number, case_state FROM cases LIMIT 5;
\d+ findings
```

### B. One-shot query without entering the shell

Useful in scripts:

```bash
docker compose exec db psql -U pharmacy -d pharmacy_db -c "\dt"
docker compose exec db psql -U pharmacy -d pharmacy_db -c "SELECT count(*) FROM findings;"
```

### C. From your Mac with a local `psql` (or a GUI like DBeaver/TablePlus)

The DB port is published to host port **5433** (see `docker-compose.yml`):

```bash
psql "postgresql://pharmacy:pharmacy@localhost:5433/pharmacy_db"
```

For a GUI, use these connection settings:

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5433` |
| Database | `pharmacy_db` (whatever `POSTGRES_DB` is in `.env`) |
| User | `pharmacy` (whatever `POSTGRES_USER` is in `.env`) |
| Password | from `.env` |

### Inspecting the test database

The test suite uses a separate database (`pharmacy_test` by default). Same
server, different DB name:

```bash
docker compose exec db psql -U pharmacy -d pharmacy_test -c "\dt"
```

Note that test data only exists *during* a test run — every test rolls back
its transaction at the end, so an idle `pharmacy_test` DB will be empty
but its tables (the schema) will still be there.

---

## 11. Glossary

| Term | Plain meaning |
|---|---|
| **ORM** | Object-Relational Mapper — work with rows as Python objects |
| **Migration** | A script that changes the DB schema |
| **Session** | One unit of work with the DB; you stage and then commit/rollback |
| **Transaction** | A group of DB ops that all succeed or all fail together |
| **Foreign key (FK)** | A column whose value must match an `id` in another table |
| **Composite unique** | "These columns together must be unique" (not each individually) |
| **CASCADE** | Delete the parent → children are deleted too |
| **RESTRICT** | Delete the parent → blocked if children still exist |
| **SET NULL** | Delete the parent → children's FK column becomes NULL |
| **Dependency injection** | FastAPI auto-providing things (like a DB session) to your function |
| **Schema (Pydantic)** | A class describing JSON shape — for validation/serialization |
| **Model (SQLAlchemy)** | A class mapping to a DB table |
| **UUID** | A 128-bit random ID — globally unique without coordination |
| **Fixture (Pytest)** | A function that sets up something a test needs |
| **Endpoint** | A URL + HTTP method combination the API responds to |
| **Status code** | 200 OK, 201 Created, 404 Not Found, 409 Conflict, 422 Validation Error |
