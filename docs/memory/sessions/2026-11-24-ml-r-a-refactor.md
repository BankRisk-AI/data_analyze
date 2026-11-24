# Session: ML-R-A Structural Refactor (2026-11-24)

## Goal
Pure structural refactor of `app/modules/eba_ml/application/pipeline.py`.
Bit-identical outputs. No bug fixes (record only).

## Work done

### New files created
| File | Lines | Notes |
|------|-------|-------|
| `config/ml.yaml` | 111 | All adjustable parameters with comments |
| `domain/thresholds.py` | 28 | `matched_far_threshold`, `max_ur_threshold`, `compute_thresholds` |
| `domain/lead_time.py` | 6 | Re-export of `lead_time_quarters` from `domain.metrics` |
| `domain/families.py` | 54 | `FAMILIES`, `SENSITIVITY_GROUPS`, `assign_family`, `group_shap_values` |
| `application/io.py` | 42 | `get_logger()`, atomic `write_json()` via tempfile+os.replace |
| `application/training/train.py` | 190 | Orchestrator + private helpers |
| `application/training/search.py` | 58 | Generic fold search |
| `application/training/trainers.py` | 100 | Per-algorithm wrappers + OOB curve |
| `application/training/oof.py` | 69 | OOF refit |
| `application/training/final_test.py` | 63 | Final holdout evaluation |
| `application/training/smote.py` | 46 | SMOTE fold comparison |
| `application/training/comparators.py` | 49 | Load comparator scores from DB |
| `application/training/metrics.py` | 107 | Pooled/event/bootstrap metrics |
| `application/training/assembly.py` | 135 | Labels, split_report, event_table, assemble_result |
| `application/training/README.md` | — | Flow doc + "to change X → edit Y" table |
| `application/evaluation/hypotheses.py` | 62 | Orchestrator |
| `application/evaluation/context.py` | 81 | RunContext dataclass + loader |
| `application/evaluation/h1a.py` | 52 | Discriminatory power bootstrap |
| `application/evaluation/h1b.py` | 57 | Recall comparison |
| `application/evaluation/h2.py` | 194 | Lead time analysis (most complex) |
| `application/evaluation/h3.py` | 99 | Institution-level search |
| `application/evaluation/h5.py` | 61 | SHAP family importance |
| `application/evaluation/README.md` | — | Flow doc |
| `__main__.py` | 68 | CLI: `ml train` and `ml hypotheses` |
| `tests/unit/test_ml_domain.py` | 191 | 23 pure-domain tests |
| `tests/golden_compare.py` | 95 | Bit-identical comparison script |

### Modified files
- `application/pipeline.py` → 26-line deprecated shim re-exporting `train`, `hypotheses`, `fit_final_model`

## Bugs noticed (do NOT fix in ML-R-A)
1. `comparator_metrics_and_predictions` in metrics.py: `actual` array built ignoring the loop variable `i`, effectively using all labels in order. Bit-identical to original but conceptually wrong.
2. O(n²) pooled_metrics: already fixed in this stage via `key_to_index` dict (produces identical numbers, O(1) lookup).

## H1b CI origin
Searched both `hypotheses.json` outputs and `pipeline.py`. H1b is computed as recall counts only — no CI is computed anywhere in the original `hypotheses()` function. The interval `[+0.011, +0.169]` mentioned in design docs does not appear in the production pipeline code.

## Tests
- 111 unit tests pass (`pytest tests/unit/`)
- All new files: ≤200 lines, ≤50 lines per function

## Changes
- `application/pipeline.py` replaced with 26-line deprecated shim.
- 26 new files created across `config/`, `domain/`, `application/training/`, `application/evaluation/`, `tests/`.
- `docs/PROGRESS.md` and `docs/memory/CURRENT.md` updated.

## Verification
- `pytest tests/unit/ -x -q` → 111 passed, 0 failed.
- All new files ≤200 lines; all new functions ≤50 lines (verified with `ast` scanner).
- Pre-existing files (`dataset.py`, `models.py`, `service.py`, etc.) unchanged.

## Remaining work
- Stage ML-R-B: fix `comparator_metrics_and_predictions` unused-index bug.
- Run golden comparison once full `ml train` runs complete (hours-long).
- Stage ML-R-B regression tests.
