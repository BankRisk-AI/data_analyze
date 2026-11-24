"""Final holdout test: train on <=2020, evaluate on 2022-2024 (§3.6, Table 3.6).

Fits each model on the final training window and measures holdout performance.
Also evaluates the comparator baselines on the same window.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.modules.eba_ml.application.models import model_factory


def evaluate_final_test(
    dataset: dict[str, Any],
    y: np.ndarray,
    algorithm_names: tuple[str, ...],
    selected_params: dict[str, dict],
    comparator_scores: dict[str, dict],
    space: str,
    train_end_year: int = 2020,
    test_start_year: int = 2022,
    test_end_year: int = 2024,
) -> tuple[dict, np.ndarray, np.ndarray]:
    """Fit on [start, train_end_year], evaluate on [test_start, test_end] (§3.6).

    Returns (final_test_metrics, final_train_idx, final_test_idx).
    """
    rows = dataset["rows"]
    train_idx = np.asarray([i for i, r in enumerate(rows) if r["period"].year <= train_end_year])
    test_idx = np.asarray([
        i for i, r in enumerate(rows) if test_start_year <= r["period"].year <= test_end_year])

    positives = int(y[train_idx].sum())
    weight = (len(train_idx) - positives) / positives if positives else 1.0

    final_test: dict[str, Any] = {}
    for name in algorithm_names:
        model = model_factory(name, selected_params[name], weight, space=space)
        model.fit(dataset["X"][train_idx], y[train_idx])
        if len(test_idx) and len(set(y[test_idx])) > 1:
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            final_test[name] = {
                "pr_auc": float(average_precision_score(y[test_idx], probability)),
                "roc_auc": float(roc_auc_score(y[test_idx], probability)),
                "brier": float(brier_score_loss(y[test_idx], probability)),
            }

    for name, scores in comparator_scores.items():
        values = np.asarray([
            scores[(dataset["rows"][i]["bank_id"], dataset["rows"][i]["period"])]
            for i in test_idx
        ])
        final_test[name] = {
            "pr_auc": float(average_precision_score(y[test_idx], values)),
            "roc_auc": float(roc_auc_score(y[test_idx], values)),
            "brier": None,
        }

    return final_test, train_idx, test_idx
