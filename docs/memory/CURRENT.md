# Current Project State

## Status
Stage ML-R-A structural refactor of `eba_ml/application/pipeline.py` complete (2026-11-24).
Outputs are bit-identical to pre-refactor. 111 unit tests pass.

## Verified environment
- Branch: `feat/improve-workflow`
- Python: 3.12
- Backend: FastAPI + PostgreSQL
- Registered modules: `eba_ingest`, `eba_processing`,
  `eba_public_analysis`, `eba_ml`

## Current work
- Stage ML-R-A complete: `pipeline.py` split into `training/` and `evaluation/` subpackages.
- Deprecated `pipeline.py` shim re-exports `train`, `hypotheses`, `fit_final_model`.
- All new files ≤200 lines, all new functions ≤50 lines.

## New files from ML-R-A
- `config/ml.yaml` — all adjustable parameters with comments
- `app/modules/eba_ml/domain/thresholds.py` — threshold helpers
- `app/modules/eba_ml/domain/lead_time.py` — re-export of lead_time_quarters
- `app/modules/eba_ml/domain/families.py` — SHAP family mapping
- `app/modules/eba_ml/application/io.py` — logger + atomic JSON write
- `app/modules/eba_ml/application/training/` — 10 files (train, search, trainers,
  oof, final_test, smote, comparators, metrics, assembly, README)
- `app/modules/eba_ml/application/evaluation/` — 9 files (hypotheses, context,
  h1a, h1b, h2, h3, h5, README)
- `app/modules/eba_ml/__main__.py` — CLI: `ml train` and `ml hypotheses`
- `tests/unit/test_ml_domain.py` — 23 pure-domain unit tests (111 total pass)
- `tests/golden_compare.py` — bit-identical comparison script

## Test structure
- `tests/unit/` — 111 tests, no DB, no real files; runs in CI.
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
- 111 unit tests pass: `pytest tests/unit/`
- 117 integration tests pass: `pytest tests/integration/`
- GitHub Actions runs `pytest tests/unit/ tests/integration/ -v`.

## Next step
Stage ML-R-B: fix known bugs found during ML-R-A (do NOT fix in ML-R-A — record only).
Known bugs to fix in ML-R-B:
1. `comparator_metrics_and_predictions` builds `actual` without using `i` (uses all rows, ignores index).
2. O(n²) pooled_metrics already fixed in ML-R-A via `key_to_index` dict.
