# EBA Analyst — Project Memory

## 1. Overview

Python backend for importing, processing, validating and analyzing EBA supervisory data.

Stack:
- Python 3.12
- FastAPI
- PostgreSQL
- psycopg2
- pytest
- SQL migrations

Configuration: `app/core/config/settings.py`.
Secrets are stored in `.env`. Never expose credentials or secret values.

## 2. Architecture

The application uses a modular architecture.

### Core — `app/core/`

Responsibilities:
- Application composition and module contracts
- Configuration and database connections
- Database migrations
- API errors and logging
- Worker infrastructure
- Shared rules and data utilities

Important files:
- `app/main.py` — application composition root
- `app/core/module.py` — ModuleSpec contract
- `app/core/config/settings.py` — settings
- `app/core/database/connection.py` — database connection
- `app/core/database/migrator.py` — migrations
- `app/core/worker/` — background worker infrastructure

### Business modules

Registered in `app/modules/__init__.py`:

| Module | Responsibility |
|---|---|
| `eba_ingest` | File ingestion, storage and staging |
| `eba_processing` | Dataset preview, profiling, validation and processing |
| `eba_public_analysis` | Analysis of promoted Chapter 4 data |
| `eba_ml` | ML datasets, experiments, models and predictions |

Each module exposes a `SPEC` based on `ModuleSpec`.
The composition root registers available routers and worker handlers.

### Shared code

Location: `app/shared/`.
Contains reusable functionality shared between modules.

## 3. Database

- PostgreSQL is the application database.
- Core migrations: `app/core/database/migrations/core/`.
- The migrator supports core and optional module migrations.
- Current module specifications use `migrations_dir=None`.
- `init_database()` applies migrations and creates the staging schema.
- `initialize_schema()` applies migrations only.
- Migration history is stored in `schema_migrations`.
- The migrator uses a PostgreSQL advisory transaction lock.

Do not assume table counts from old documentation. Inspect migrations.

## 4. Ingestion and processing

EBA source files are ingested and staged for processing.
Original files and staging data have separate responsibilities.

Verify supported file types and validation rules in source code before changing them.

## 5. Background jobs

Worker entry points:
- `app/worker.py`
- `app/core/worker/`

The worker registers handlers, claims pending jobs using PostgreSQL row locking,
tracks attempts and progress, uses heartbeats and recovers stale jobs.

Verify the handler registry before changing job types.

## 6. CLI and development

Entry point: `python -m app`

Available commands include:
`serve`, `worker`, `init-db`, `openapi`, `dictionary`, `dimensions`,
`panel`, `rules`, `figures`, `evaluate`, `ml`, `reset-data`,
`import-edition`, `import-all`, `smoke`, `preflight`, `preflight-all`.

Useful commands:
- `make dev`
- `make worker`
- `make test`
- `.venv/bin/python -m app --help`

Important discrepancy:
`init-db` requires `--target {test,prod}`, while the current Makefile
`initdb` target does not pass this argument. Verify before using it.

## 7. Tests and database safety

- `pytest.ini` excludes tests marked `slow` by default.
- Run all tests with `.venv/bin/python -m pytest -v -m ""`.
- Development dependencies are in `requirements-dev.txt`.
- Some tests require prepared EBA files or external ML artifacts.

CRITICAL:
`tests/conftest.py` drops and recreates the `public` and `staging`
schemas when `TEST_DATABASE_URL` is configured.

`TEST_DATABASE_URL` MUST point exclusively to a disposable test database.
Never point it to production or a database containing important data.

Without `TEST_DATABASE_URL`, database-dependent tests are skipped.

## 8. Documentation

- `README.md` — project introduction and setup
- `docs/PROGRESS.md` — historical development progress
- `docs/ANALIZA_COD.md` — code analysis
- `docs/PERF.md` — performance notes
- `docs/openapi.yaml` — generated API specification
- `.github/prompts/prompt.txt` — user's single task prompt

Documentation can become outdated. Verify implementation against source code.
Do not create additional task prompt files.

## 9. Development conventions

- Inspect existing implementation before modifying it.
- Keep modules independent and reusable.
- Centralize shared functionality and configuration.
- Avoid duplicated business logic.
- Preserve API contracts unless the task requires changes.
- Add or update relevant tests.
- Do not modify unrelated files.
- Do not commit or push unless explicitly requested.

## 10. Shared AI memory

Memory location: `docs/memory/`

- `CURRENT.md` — verified current state and next step
- `PROJECT.md` — stable architecture and project facts
- `DECISIONS.md` — durable technical decisions
- `sessions/` — concise session history

Follow `AGENTS.md` when reading and updating memory.
