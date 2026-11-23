# GitHub Copilot Instructions

## Shared instructions

Follow `AGENTS.md` as the authoritative source of shared AI agent rules.

Before working:
1. Read `AGENTS.md`.
2. Read `docs/memory/CURRENT.md`.
3. Read relevant sections of `docs/memory/PROJECT.md`.
4. Consult `docs/memory/DECISIONS.md` when relevant.

Do not load the full repository or session history.
Inspect only files relevant to the current task.
Use targeted searches and concise command output.

## Project-specific rules

- Python 3.12, FastAPI and PostgreSQL.
- Application composition root: `app/main.py`.
- Module registry: `app/modules/__init__.py`.
- Registered modules: `eba_ingest`, `eba_processing`,
  `eba_public_analysis`, `eba_ml`.
- Shared module contract: `app/core/module.py`.
- Architecture rules: `tests/architecture/test_layering.py`.
- SQL migrations: `app/core/database/migrations/core/`.
- OpenAPI specification: `docs/openapi.yaml`.

Inspect source code and tests before changing implementation.
Do not rely on outdated documentation for current architecture.

## Build and test

Useful commands:
- `make dev`
- `make worker`
- `make test`
- `.venv/bin/python -m app --help`

Run all tests, including slow tests:
`.venv/bin/python -m pytest -v -m ""`

Run focused tests when possible.

## Database safety

CRITICAL:
`tests/conftest.py` drops and recreates the `public` and `staging`
schemas in the database specified by `TEST_DATABASE_URL`.

`TEST_DATABASE_URL` MUST point exclusively to a disposable test database.
Never use production or a database containing important data.

Without `TEST_DATABASE_URL`, database-dependent tests are skipped.

The CLI `init-db` requires `--target {test,prod}`.
Check command help before database operations.
The current Makefile `initdb` target does not pass this argument.

## OpenAPI

After relevant API changes, regenerate the specification:
`.venv/bin/python -m app openapi --out docs/openapi.yaml`

## Memory maintenance

At the end of each work session:
- Update `docs/memory/CURRENT.md`.
- Append a concise note to `docs/memory/sessions/`.
- Update stable project facts and decisions only when necessary.
- Run `.venv/bin/python scripts/validate_memory.py`.

Never expose `.env` secrets.
Do not commit or push unless explicitly requested.
