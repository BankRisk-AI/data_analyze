# Current Project State

## Status
Cross-agent memory system implemented and validated.
Application business logic was not changed.

## Verified environment
- Branch: `feat/improve-workflow`
- Last inspected commit: `ae30c46`
- Python: 3.12
- Backend: FastAPI + PostgreSQL
- Registered modules: `eba_ingest`, `eba_processing`,
  `eba_public_analysis`, `eba_ml`

## Current work
- Test refactoring completed: tests reorganized into unit/, integration/, data_processing/.

## Test structure
- `tests/unit/` — 63 tests, no DB, no real files; runs in CI.
- `tests/integration/` — 117 tests, require `TEST_DATABASE_URL`; runs in CI.
- `tests/data_processing/` — 5 tests with real EBA files; excluded from CI and default run.
- `tests/conftest.py` — shared fixtures (`db`, `database_url`, `write_csv`).

## Memory system
- Shared rules: `AGENTS.md`
- Agent instructions: `CLAUDE.md`, `GEMINI.md`,
  `.github/copilot-instructions.md`
- Project reference: `docs/memory/PROJECT.md`
- Current state: this file
- Decisions: `docs/memory/DECISIONS.md`
- Session history: `docs/memory/sessions/`
- Validator: `scripts/validate_memory.py`
- Automated test: `tests/unit/test_memory_validation.py`

## Important constraints
- Keep `.github/prompts/prompt.txt` as the single task prompt.
- Never expose `.env` secrets.
- `TEST_DATABASE_URL` must point only to a disposable test database.
- Test setup drops and recreates `public` and `staging`.
- Do not commit or push unless explicitly requested.

## Verification
- 63 unit tests pass: `pytest tests/unit/`
- 117 integration tests pass: `pytest tests/integration/`
- `pytest tests/` collects 180 tests (data_processing excluded by addopts).
- GitHub Actions runs `pytest tests/unit/ tests/integration/ -v`.

## Next step
Confirm the next EBA Analyst development task with the user.
