"""Pooled and comparator metrics computation helpers (§3.5).

Called by train.py orchestrator after OOF refitting and comparator loading.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.domain.metrics import _classification_metrics, _cluster_bootstrap


def compute_pooled_metrics(
    dataset: dict[str, Any], y: np.ndarray,
    predictions: dict[str, dict], key_to_index: dict,
) -> dict[str, dict]:
    """Compute pooled OOF PR-AUC, ROC-AUC, Brier for each ML model (§3.5)."""
    from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
    pooled: dict[str, dict] = {}
    for name, values in predictions.items():
        keys = list(values)
        actual = np.asarray([y[key_to_index[key]] for key in keys])
        probability = np.asarray([values[key] for key in keys])
        pooled[name] = {
            "pr_auc": float(average_precision_score(actual, probability)),
            "roc_auc": float(roc_auc_score(actual, probability))
            if len(set(actual)) > 1 else None,
            "brier": float(brier_score_loss(actual, probability)),
        }
    return pooled


def comparator_metrics_and_predictions(
    dataset: dict[str, Any], y: np.ndarray,
    comparator_scores: dict[str, dict],
) -> tuple[dict, dict]:
    """Compute pooled metrics and string-keyed predictions for comparators (§3.3)."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    rows = dataset["rows"]
    metrics: dict[str, dict] = {}
    for name, scores in comparator_scores.items():
        actual = np.asarray([y[i] for i, row in enumerate(rows)])
        values = np.asarray([scores[(row["bank_id"], row["period"])] for row in rows])
        metrics[name] = {
            "pr_auc": float(average_precision_score(actual, values)),
            "roc_auc": float(roc_auc_score(actual, values)),
            "brier": None,
        }
    comp_predictions = {
        name: {
            f"{row['bank_id']}:{row['period'].isoformat()}":
            float(scores[(row["bank_id"], row["period"])])
            for row in rows
        }
        for name, scores in comparator_scores.items()
    }
    return metrics, comp_predictions


def compute_event_metrics(
    dataset: dict[str, Any], y: np.ndarray,
    predictions: dict[str, dict], comparator_scores: dict[str, dict],
    algorithm_names: tuple, key_to_index: dict,
) -> dict[str, dict]:
    """Compute classification metrics for all models and comparators (§3.5)."""
    rows = dataset["rows"]
    event_metrics: dict[str, dict] = {}
    for name, scores in comparator_scores.items():
        event_metrics[name] = _classification_metrics(
            y, np.asarray([scores[(row["bank_id"], row["period"])] for row in rows]))
    for name in algorithm_names:
        values = predictions[name]
        keys = list(values)
        actual = np.asarray([y[key_to_index[key]] for key in keys])
        probability = np.asarray([values[key] for key in keys])
        event_metrics[name] = _classification_metrics(actual, probability)
    return event_metrics


def compute_bootstrap_cis(
    dataset: dict[str, Any], y: np.ndarray,
    predictions: dict[str, dict], comparator_scores: dict[str, dict],
    algorithm_names: tuple, key_to_index: dict,
) -> dict[str, list]:
    """Compute clustered bootstrap CIs for ML vs comparator advantage (§3.5)."""
    rows = dataset["rows"]
    pooled_arrays: dict[str, tuple] = {}
    for name, values in predictions.items():
        keys = list(values)
        indices = np.asarray([key_to_index[key] for key in keys])
        pooled_arrays[name] = (
            y[indices],
            np.asarray(list(values.values())),
            np.asarray([rows[i]["bank_id"] for i in indices]),
            indices,
        )
    cis: dict[str, list] = {}
    for reference in ("v1.1 score", "B4"):
        ref_scores = np.asarray([
            comparator_scores[reference][(r["bank_id"], r["period"])] for r in rows])
        for name in algorithm_names:
            actual, scores, banks, indices = pooled_arrays[name]
            cis[f"{name}_vs_{reference}"] = _cluster_bootstrap(
                actual, scores, ref_scores[indices], banks)
    return cis
