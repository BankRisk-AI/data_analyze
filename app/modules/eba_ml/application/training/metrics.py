"""Pooled OOF metrics computation helpers (§3.5).

Called by train.py orchestrator after OOF refitting.
Comparator metrics and bootstrap CIs have been removed (T-1); R0/R1 added in T-2.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.domain.metrics import _classification_metrics


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


def compute_classification_metrics(
    dataset: dict[str, Any], y: np.ndarray,
    predictions: dict[str, dict], algorithm_names: tuple, key_to_index: dict,
) -> dict[str, dict]:
    """Compute classification metrics (hit rate, FAR, PR-AUC, ROC-AUC) for ML models (§3.5)."""
    event_metrics: dict[str, dict] = {}
    for name in algorithm_names:
        values = predictions[name]
        keys = list(values)
        actual = np.asarray([y[key_to_index[key]] for key in keys])
        probability = np.asarray([values[key] for key in keys])
        event_metrics[name] = _classification_metrics(actual, probability)
    return event_metrics
