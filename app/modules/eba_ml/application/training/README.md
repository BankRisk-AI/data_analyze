# Training flow

## Steps (in order)

1. `build_dataset` — load panel rows from DB, build feature matrix X and target labels y
2. `save_dataset` — write compressed .npz + manifest JSON to out_dir
3. `_run_all_searches` → `run_fold_search` per algorithm — grid search over folds
4. `oob_curve` (RF only) — select n_estimators via OOB score
5. `refit_folds` — OOF refit + SMOTE comparison; build predictions dict
6. `_compute_pooled_metrics` — pooled OOF PR-AUC/ROC-AUC/Brier per model
7. `load_comparator_scores` — query alert table for v1.1, B4, B2 baselines
8. `_comparator_metrics_and_predictions` — pooled metrics for comparators
9. `_compute_event_metrics` / `_compute_bootstrap_cis` — classification metrics and CIs
10. `evaluate_final_test` — fit on ≤2020, evaluate on 2022–2024
11. `_select_and_refit_champion` — pick best model by OOF PR-AUC, refit on training data
12. `_compute_shap` — mean-absolute SHAP importances
13. `_build_event_table` — per-event detection using threshold-matched scores
14. `write_json` — atomic JSON save to out_dir/results_{target}_{grid}[_robust].json

## To change X → edit Y

| What to change | File to edit |
|---|---|
| Search spaces (hyperparameter grids) | `config/ml.yaml` → `search_spaces` |
| Search budget (configs per model) | `config/ml.yaml` → `search_budget` |
| Cross-validation fold years | `config/ml.yaml` → `folds.test_years` |
| Final test window | `config/ml.yaml` → `final_test` |
| RF OOB candidates | `config/ml.yaml` → `oob_n_estimators` |
| Event window (months) | `config/ml.yaml` → `event_window_months` |
| Comparator profile SHA | `config/ml.yaml` → `comparator_profile_sha` |
| Add a model | `trainers.py` → add `train_XYZ`, add to `TRAINERS` |
| Change class-weight formula | `oof.py` → `refit_folds` weight line |
| Change SMOTE strategy | `smote.py` → `smote_fold_comparison` |
| Change comparator baselines | `comparators.py` → `load_comparator_scores` |
| Change holdout split years | `final_test.py` → `evaluate_final_test` defaults |
