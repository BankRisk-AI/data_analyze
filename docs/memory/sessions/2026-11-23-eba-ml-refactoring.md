# Session 2026-11-23 — eba_ml architectural refactoring

## Goal
Refactor `app/modules/eba_ml` into a clean 7-layer architecture. Split the 858-line `ml_pipeline.py` god-object, fix broken predictions endpoint, add T1–T5 unit tests.

## Changes

**New files:**
- `domain/exceptions.py` — ProtectedModelError
- `domain/metrics.py` — 7 pure statistical functions (holm_adjust, equal_alert_volume_recall, lead_time_quarters, _classification_metrics, _cluster_bootstrap, _hyp_bootstrap, _hyp_wilcoxon)
- `application/dataset.py` — dataset building functions (_months, _approved_ids, _event_ids, _target_rows, build_dataset, save_dataset, folds)
- `application/models.py` — model_factory, _search_configs; SEED=20261121, SEARCH_CONFIGURATIONS=60
- `application/pipeline.py` — renamed from ml_pipeline.py; train, hypotheses, fit_final_model

**Modified files:**
- `domain/constants.py` — added FEATURES tuple
- `application/lifecycle.py` — ModelLifecycle class → 3 standalone functions
- `application/service.py` — added list_predictions(); uses lifecycle.* functions
- `presentation/api.py` — predictions endpoint calls service.list_predictions()
- `app/ml.py` — star import replaced with explicit re-exports
- `app/__main__.py` — updated imports to pipeline.py
- `backfill.py`, `worker_handlers.py` — updated imports

**Deleted files:**
- `application/ml_pipeline.py` (858 lines)

**Tests added:**
- `tests/unit/test_ml_targets.py` — 23 tests for T1-T5-T5_noT1 labelling logic
- `tests/unit/test_ml_module.py` — +2 tests for list_predictions()

## Key decisions
- `_target_rows()` refactored to pure function: `(rows, event_ids, events, event_start_months)`
- SEED and SEARCH_CONFIGURATIONS defined in models.py; re-exported by pipeline.py
- domain/metrics.py has no imports from application/infrastructure/presentation
- EU_EBA_V1_1_PROFILE_SHA extracted as named constant in pipeline.py

## Verification
- 88 unit tests pass
- 117 integration tests pass
- SPEC import OK
- git diff --check clean
- No ml_pipeline references remain
- No star imports in app/ml.py

## Remaining work
None. All 8 refactoring stages completed and verified.
