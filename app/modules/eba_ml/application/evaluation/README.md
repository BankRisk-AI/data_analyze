# Evaluation flow

## Steps (in order)

1. `load_run_context` — load results JSON + rebuild dataset + build index arrays; labels from stored artifact rows
2. `compute_h1a` — pairwise model comparison (RF vs LR, XGB vs LR): bootstrap dPR/dROC, Holm p-values, fold Wilcoxon
3. `compute_h3` — levels-only vs levels+trends: bootstrap dPR and fold Wilcoxon
4. `compute_h5` — grouped SHAP importances; Capital+Earnings rank check
5. `write_json` — atomic save to run_dir/hypotheses.json

**Removed in T-1:** H1b (equal-alert-volume recall vs v1.1) and H2 (LOEO per-event
lead times). Both will be rewritten in T-2 for E2/E3 labels and R0/R1 benchmarks.

## To change X → edit Y

| What to change | File to edit |
|---|---|
| Bootstrap replicates | `config/ml.yaml` → `bootstrap_replicates` |
| H3 search budget | `config/ml.yaml` → `h3_budget` |
| SHAP families | `config/ml.yaml` → `shap_families`; `domain/families.py` → `FAMILIES` |
| Sensitivity grouping | `config/ml.yaml` → `shap_sensitivity_groups`; `domain/families.py` → `SENSITIVITY_GROUPS` |
| Add a hypothesis | Add `hN.py`, import and call in `hypotheses.py` |
