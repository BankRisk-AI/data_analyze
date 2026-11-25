"""Split report and result-dict assembly (§3.5).

Called by train.py orchestrator.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import SEARCH_CONFIGURATIONS, SEED


def build_split_report(rows: list[dict], y: np.ndarray,
                       final_train_idx: np.ndarray, final_test_idx: np.ndarray,
                       ) -> list[dict]:
    """Build per-fold split statistics including the final test entry (Table 3.5)."""
    report = []
    for fold_number, (train_indices, test_indices) in enumerate(folds(rows), 1):
        n_train, n_test = len(train_indices), len(test_indices)
        if n_test == 0:
            continue
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
    })
    return report


def assemble_result(
    grid: str, space: str, label: str,
    dataset: dict[str, Any], y: np.ndarray,
    algorithm_names: tuple,
    search_results: dict, selected_params: dict,
    split_report: list, fold_metrics: list, smote_metrics: list,
    pooled_metrics: dict, final_test: dict, test_predictions: dict,
    oob_curve_data: list, predictions: dict,
    label_meta: dict, r1_margin: float, r1_f2: float,
    operating_point_threshold: float, operating_point_f2: float,
    selected_model: str,
) -> dict[str, Any]:
    """Assemble the results dict for JSON serialisation (§3.5)."""
    return {
        "grid": grid, "seed": SEED, "space": space, "label": label,
        "search_configurations": SEARCH_CONFIGURATIONS,
        "search_configuration_counts": {
            name: len(search_results[name]) for name in algorithm_names},
        "search": search_results, "selected_parameters": selected_params,
        "selected_model": selected_model,
        "panel_hash": dataset["panel_hash"], "fold_metrics": fold_metrics,
        "split_report": split_report, "smote_metrics": smote_metrics,
        "pooled_metrics": pooled_metrics, "final_test": final_test,
        "test_predictions": test_predictions,
        "oob_curve": oob_curve_data,
        "predictions": predictions, "columns": dataset["columns"],
        "label_meta": label_meta,
        "r1_margin": r1_margin, "r1_f2": r1_f2,
        "operating_point_threshold": operating_point_threshold,
        "operating_point_f2": operating_point_f2,
        "rows": _make_row_records(dataset["rows"], y),
    }


def _make_row_records(rows: list[dict], y: np.ndarray) -> list[dict]:
    """Persist per-row diagnostics (bank_id, period, ratios, label) for offline analysis."""
    fold_of: dict[int, int | str] = {}
    for fold_no, (_, test_idx) in enumerate(folds(rows), 1):
        for i in test_idx:
            fold_of[i] = fold_no
    # Final-test rows (year >= 2022) not in any OOF fold
    for i, row in enumerate(rows):
        if row["period"].year >= 2022:
            fold_of.setdefault(i, "final_test")
    return [
        {
            "bank_id": row["bank_id"],
            "period": row["period"].isoformat(),
            "fold": fold_of.get(i, "train_only"),
            "cet1_ratio": row.get("cet1_ratio"),
            "tier1_ratio": row.get("tier1_ratio"),
            "total_capital_ratio": row.get("total_capital_ratio"),
            "label": int(y[i]),
        }
        for i, row in enumerate(rows)
    ]
