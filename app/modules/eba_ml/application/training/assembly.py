"""Dataset labelling, split report, event table and result-dict assembly (§3.5, §3.6).

Called by train.py orchestrator.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.modules.eba_ml.application.dataset import _months, folds
from app.modules.eba_ml.application.models import SEED, SEARCH_CONFIGURATIONS


def build_labels(dataset: dict[str, Any], target: str) -> np.ndarray:
    """Build the binary label array y from dataset targets (§3.5)."""
    return np.asarray(
        [(row["bank_id"], row["period"]) in dataset["targets"][target]
         for row in dataset["rows"]], dtype=int)


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


def build_event_table(
    conn, dataset: dict[str, Any],
    predictions: dict[str, dict], selected_name: str,
    comparator_scores: dict[str, dict],
) -> list[dict]:
    """Build per-event detection table using selected model scores (§3.6, H2)."""
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    selected_scores = predictions[selected_name]
    score_values = np.asarray(list(selected_scores.values()))
    red_share = np.mean(np.asarray([
        comparator_scores["v1.1 score"][(row["bank_id"], row["period"])] > 0
        for row in dataset["rows"]]))
    thresholds = {
        "matched_far": float(np.quantile(score_values, max(0.0, 1.0 - red_share))),
        "max_ur_0_9": float(np.quantile(score_values, 0.90)),
    }
    event_table = []
    for event in catalogue.get("events", []):
        if event.get("set") != "primary" or event.get("status") != "included":
            continue
        bank_id = bank_ids.get(str(event["bank_lei"]).strip())
        event_date = date.fromisoformat(str(event["event_date"]))
        values = [p for key, p in selected_scores.items()
                  if bank_id is not None and key.startswith(f"{bank_id}:")
                  and _months(event_date, -12) <= date.fromisoformat(key.split(":", 1)[1])
                  <= _months(event_date, -3)]
        probability = max(values) if values else None
        event_table.append({
            "event": event.get("name", event.get("bank_lei")),
            "probability": probability,
            "matched_far": probability is not None and probability >= thresholds["matched_far"],
            "max_ur_0_9": probability is not None and probability >= thresholds["max_ur_0_9"],
            "thresholds": thresholds,
        })
    return event_table


def assemble_result(
    target: str, grid: str, space: str,
    dataset: dict[str, Any], y: np.ndarray,
    selected_name: str, algorithm_names: tuple,
    search_results: dict, selected_params: dict,
    split_report: list, fold_metrics: list, smote_metrics: list,
    pooled_metrics: dict, final_test: dict, shap_importance: dict,
    event_metrics: dict, bootstrap_cis: dict, event_table: list,
    oob_curve_data: list, predictions: dict, comparator_predictions: dict,
) -> dict[str, Any]:
    """Assemble the full results dict for JSON serialisation (§3.5)."""
    return {
        "target": target, "grid": grid, "seed": SEED, "space": space,
        "search_configurations": SEARCH_CONFIGURATIONS,
        "search_configuration_counts": {
            name: len(search_results[name]) for name in algorithm_names},
        "search": search_results, "selected_parameters": selected_params,
        "panel_hash": dataset["panel_hash"], "fold_metrics": fold_metrics,
        "split_report": split_report,
        "target_counts_before": dataset["target_counts_before"],
        "target_counts_after": dataset["target_counts_after"],
        "smote_metrics": smote_metrics,
        "pooled_metrics": pooled_metrics, "final_test": final_test,
        "selected_model": selected_name, "shap_importance": shap_importance,
        "event_metrics": event_metrics,
        "bootstrap_cis": bootstrap_cis,
        "event_table": event_table,
        "oob_curve": oob_curve_data,
        "predictions": predictions, "columns": dataset["columns"],
        "comparator_predictions": comparator_predictions,
        "rows": [{"bank_id": row["bank_id"], "period": row["period"].isoformat(),
                  "label": int(y[i])}
                 for i, row in enumerate(dataset["rows"])],
    }
