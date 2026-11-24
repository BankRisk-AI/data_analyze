"""Split report and result-dict assembly (§3.5).

Called by train.py orchestrator.
Event table, comparator predictions, event metrics, bootstrap CIs, and
SHAP importances removed in T-1 (rule benchmarks become R0/R1 in T-2).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import SEED, SEARCH_CONFIGURATIONS


def build_split_report(rows: list[dict], y: np.ndarray,
                       final_train_idx: np.ndarray, final_test_idx: np.ndarray,
                       ) -> list[dict]:
    """Build per-fold split statistics including the final test entry (Table 3.5)."""
    report = []
    for fold_number, (train_indices, test_indices) in enumerate(folds(rows), 1):
        test_year = 2016 + fold_number
        n_train, n_test = len(train_indices), len(test_indices)
        total = n_train + n_test
        report.append({
            "fold": fold_number, "train_rows": int(n_train),
            "train_positives": int(y[train_indices].sum()),
            "test_rows": int(n_test), "test_positives": int(y[test_indices].sum()),
            "train_share_percent": float(100 * n_train / total) if total else 0.0,
            "train_positive_rate_percent": float(100 * y[train_indices].mean())
            if n_train else 0.0,
            "test_positive_rate_percent": float(100 * y[test_indices].mean())
            if n_test else 0.0,
            "embargo_year": test_year - 1,
        })
    n_ft_train, n_ft_test = len(final_train_idx), len(final_test_idx)
    report.append({
        "fold": "final_test", "train_rows": int(n_ft_train),
        "train_positives": int(y[final_train_idx].sum()),
        "test_rows": int(n_ft_test), "test_positives": int(y[final_test_idx].sum()),
        "train_share_percent": float(100 * n_ft_train / (n_ft_train + n_ft_test))
        if n_ft_train + n_ft_test else 0.0,
        "train_positive_rate_percent": float(100 * y[final_train_idx].mean())
        if n_ft_train else 0.0,
        "test_positive_rate_percent": float(100 * y[final_test_idx].mean())
        if n_ft_test else 0.0,
        "embargo_year": 2021,
    })
    return report


def assemble_result(
    grid: str, space: str,
    dataset: dict[str, Any], y: np.ndarray,
    algorithm_names: tuple,
    search_results: dict, selected_params: dict,
    split_report: list, fold_metrics: list, smote_metrics: list,
    pooled_metrics: dict, final_test: dict,
    oob_curve_data: list, predictions: dict,
) -> dict[str, Any]:
    """Assemble the results dict for JSON serialisation (§3.5).

    Comparator predictions, event metrics, bootstrap CIs, event table,
    and SHAP importances are not included (removed in T-1).
    """
    return {
        "grid": grid, "seed": SEED, "space": space,
        "search_configurations": SEARCH_CONFIGURATIONS,
        "search_configuration_counts": {
            name: len(search_results[name]) for name in algorithm_names},
        "search": search_results, "selected_parameters": selected_params,
        "panel_hash": dataset["panel_hash"], "fold_metrics": fold_metrics,
        "split_report": split_report,
        "smote_metrics": smote_metrics,
        "pooled_metrics": pooled_metrics, "final_test": final_test,
        "oob_curve": oob_curve_data,
        "predictions": predictions, "columns": dataset["columns"],
        "rows": [{"bank_id": row["bank_id"], "period": row["period"].isoformat(),
                  "label": int(y[i])}
                 for i, row in enumerate(dataset["rows"])],
    }
