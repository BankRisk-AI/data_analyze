# Training flow

## Steps (in order)

1. `build_dataset` — load panel rows from DB, build feature matrix X (no targets)
2. `save_dataset` — write compressed .npz + manifest JSON to out_dir
3. `_run_all_searches` → `run_fold_search` per algorithm — grid search over folds
4. `oob_curve` (RF only) — select n_estimators via OOB score
5. `refit_folds` — OOF refit + SMOTE comparison; build predictions dict
6. `compute_pooled_metrics` — pooled OOF PR-AUC/ROC-AUC/Brier per model
7. `evaluate_final_test` — fit on ≤2020, evaluate on 2022–2024
8. `build_split_report` — per-fold row/positive counts including final test
9. `assemble_result` — compose result dict (predictions, rows with stored labels)
10. `write_json` — atomic JSON save to out_dir/results_{grid}[_robust].json

**Removed in T-1:** comparators (v1.1/B4/B2), event table, event metrics,
bootstrap CIs, SHAP inside training, `fit_final_model`, `build_labels`.
T-2 will add E2/E3 label functions; `train()` already accepts `y: np.ndarray`.

## To change X → edit Y

| What to change | File to edit |
|---|---|
| Search spaces (hyperparameter grids) | `config/ml.yaml` → `search_spaces` |
| Search budget (configs per model) | `config/ml.yaml` → `search_budget` |
| Cross-validation fold years | `config/ml.yaml` → `folds.test_years` |
| Final test window | `config/ml.yaml` → `final_test` |
| RF OOB candidates | `config/ml.yaml` → `oob_n_estimators` |
| Add a model | `trainers.py` → add `train_XYZ`, add to `TRAINERS` |
| Change class-weight formula | `oof.py` → `refit_folds` weight line |
| Change SMOTE strategy | `smote.py` → `smote_fold_comparison` |
| Change holdout split years | `final_test.py` → `evaluate_final_test` defaults |
