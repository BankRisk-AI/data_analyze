# Evaluation flow

## Steps (in order)

1. `load_run_context` — load results JSON + rebuild dataset + build index arrays
2. `compute_h1a` — pairwise model comparison (RF vs LR, XGB vs LR): bootstrap dPR/dROC, Holm p-values, fold Wilcoxon
3. `compute_h1b` — equal-alert-volume recall: ml_recall vs v1_1_recall on OOF periods
4. `compute_h2` — per-event lead times t_A, t_B, L; Wilcoxon on nonzero L
5. `compute_h3` — levels-only vs levels+trends: bootstrap dPR and fold Wilcoxon
6. `compute_h5` — grouped SHAP importances; Capital+Earnings rank check
7. `write_json` — atomic save to run_dir/hypotheses.json

## To change X → edit Y

| What to change | File to edit |
|---|---|
| Bootstrap replicates | `config/ml.yaml` → `bootstrap_replicates` |
| H3 search budget | `config/ml.yaml` → `h3_budget` |
| LOEO limit (quick mode) | `config/ml.yaml` → `loeo_limit_quick` |
| SHAP families | `config/ml.yaml` → `shap_families`; `domain/families.py` → `FAMILIES` |
| Sensitivity grouping | `config/ml.yaml` → `shap_sensitivity_groups`; `domain/families.py` → `SENSITIVITY_GROUPS` |
| Comparator profile SHA | `config/ml.yaml` → `comparator_profile_sha` |
| Add a hypothesis | Add `hN.py`, import and call in `hypotheses.py` |
| Event window (H2) | `config/ml.yaml` → `event_window_months` |
