"""Final holdout test: train on <=2020, evaluate on 2022-2024 (§3.6, Table 3.6).

Fits each model on the final training window and measures holdout performance.
Also returns per-row predictions for H1b and H2 evaluation.
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
    space: str,
    train_end_year: int = 2020,
    test_start_year: int = 2022,
    test_end_year: int = 2024,
) -> tuple[dict, dict, np.ndarray, np.ndarray]:
    """Fit models on [start, train_end_year] and evaluate on [test_start, test_end].

    Returns (final_test_metrics, test_predictions, final_train_idx, final_test_idx).
    final_test_metrics: {name: {pr_auc, roc_auc, brier}}.
    test_predictions: {name: {"bank_id:period": score}} for the test set.
    """
    rows = dataset["rows"]
    train_idx = np.asarray(
        [i for i, row in enumerate(rows) if row["period"].year <= train_end_year],
        dtype=int)
    test_idx = np.asarray(
        [i for i, row in enumerate(rows)
         if test_start_year <= row["period"].year <= test_end_year],
        dtype=int)
    if len(train_idx) == 0:
        raise ValueError(
            f"evaluate_final_test: no training rows with year <= {train_end_year}")
    if len(test_idx) == 0:
        raise ValueError(
            f"evaluate_final_test: no test rows in {test_start_year}–{test_end_year}")

    positives = int(y[train_idx].sum())
    weight = (len(train_idx) - positives) / positives if positives else 1.0

    final_test: dict[str, Any] = {}
    test_predictions: dict[str, dict] = {}
    for name in algorithm_names:
        model = model_factory(name, selected_params[name], weight, space=space)
        model.fit(dataset["X"][train_idx], y[train_idx])
        if len(test_idx):
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            test_predictions[name] = {
                f"{rows[i]['bank_id']}:{rows[i]['period'].isoformat()}": float(p)
                for i, p in zip(test_idx, probability)
            }
            if len(set(y[test_idx])) > 1:
                final_test[name] = {
                    "pr_auc": float(average_precision_score(y[test_idx], probability)),
                    "roc_auc": float(roc_auc_score(y[test_idx], probability)),
                    "brier": float(brier_score_loss(y[test_idx], probability)),
                }

    return final_test, test_predictions, train_idx, test_idx
