# Current Project State

## Status
Stage T-1 cleanup of `eba_ml` complete (2026-11-24).
All T1--T5 target code, LOEO, comparators, event metrics, bootstrap CIs,
SHAP-in-training, `fit_final_model`, `h1b.py`, and `h2.py` removed.
83 unit tests pass.

## Verified environment
- Branch: `feat/improve-workflow`
- Python: 3.12
- Backend: FastAPI + PostgreSQL
- Registered modules: `eba_ingest`, `eba_processing`,
  `eba_public_analysis`, `eba_ml`

## Current work
- T-1 complete: ML code aligned with thesis §3 (E2/E3 targets, no comparators).
- `train()` now accepts `y: np.ndarray` externally; `cmd_train` and `_train`
  handler stub `NotImplementedError("T-2: ...")`.
- `score_panel` job and all API routes still work.
- HSH confirmed: bank_id 24 (Hamburg Commercial Bank AG) == bank_id 185
  (HSH Beteiligungs Management GmbH) via `previous_leis` crosswalk.

## Active files in eba_ml
- `config/ml.yaml` — all adjustable parameters
- `app/modules/eba_ml/domain/constants.py` — GRIDS, ALGORITHMS, FEATURE_SETS, THRESHOLDS, MAX_BUDGET, FEATURES (no TARGETS)
- `app/modules/eba_ml/domain/families.py` — SHAP family mapping
- `app/modules/eba_ml/application/io.py` — logger + atomic JSON write
- `app/modules/eba_ml/application/dataset.py` — build_dataset (no targets), save_dataset, folds
- `app/modules/eba_ml/application/training/` — train, search, trainers, oof, final_test, smote, metrics, assembly, README
- `app/modules/eba_ml/application/evaluation/` — hypotheses (H1a/H3/H5 only), context, h1a, h3, h5, README
- `app/modules/eba_ml/__main__.py` — CLI: `ml train` (stubbed), `ml hypotheses`
- `app/modules/eba_ml/application/worker_handlers.py` — _train stubbed; score_panel works
- `app/modules/eba_ml/application/backfill.py` — stubbed NotImplementedError
- `app/modules/eba_ml/application/service.py` — no TARGETS; _validate checks grid only

## Deleted in T-1
- `app/modules/eba_ml/domain/thresholds.py`
- `app/modules/eba_ml/domain/lead_time.py`
- `app/modules/eba_ml/application/pipeline.py` (deprecated shim)
- `app/modules/eba_ml/application/training/comparators.py`
- `app/modules/eba_ml/application/evaluation/h1b.py`
- `app/modules/eba_ml/application/evaluation/h2.py`

## Test structure
- `tests/unit/` — 83 tests, no DB, no real files; runs in CI.
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
- 83 unit tests pass: `pytest tests/unit/`
- 117 integration tests pass: `pytest tests/integration/`
- GitHub Actions runs `pytest tests/unit/ tests/integration/ -v`.

## Next step
T-2: add E2/E3 label functions, R0/R1 baselines, F2 operating point, rewrite
H1b (equal-volume recall) and H2 (lead time) for E2/E3 and R0/R1.
HSH crosswalk: bank_id 24 and 185 need a crosswalk group (same institution).
