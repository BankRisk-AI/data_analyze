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
- Cross-agent memory setup completed; final verification in progress.

## Memory system
- Shared rules: `AGENTS.md`
- Agent instructions: `CLAUDE.md`, `GEMINI.md`,
  `.github/copilot-instructions.md`
- Project reference: `docs/memory/PROJECT.md`
- Current state: this file
- Decisions: `docs/memory/DECISIONS.md`
- Session history: `docs/memory/sessions/`
- Validator: `scripts/validate_memory.py`
- Automated test: `tests/test_memory_validation.py`

## Important constraints
- Keep `.github/prompts/prompt.txt` as the single task prompt.
- Never expose `.env` secrets.
- `TEST_DATABASE_URL` must point only to a disposable test database.
- Test setup drops and recreates `public` and `staging`.
- Do not commit or push unless explicitly requested.

## Verification
- Memory validator passes.
- Automated pytest for memory validation passes.
- GitHub Actions runs `pytest tests/`, which includes the memory test.

## Next step
Confirm the next EBA Analyst development task with the user.
