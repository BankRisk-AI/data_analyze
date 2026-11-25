"""Out-of-fold refitting: build OOF predictions and fold metrics (§3.5).

Refits each model on each fold's training split (with correct class weight)
and records per-fold PR-AUC, ROC-AUC, Brier score, and optionally SMOTE comparison.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import model_factory
from app.modules.eba_ml.application.training.smote import smote_fold_comparison


def refit_folds(
    dataset: dict[str, Any],
    y: np.ndarray,
    algorithm_names: tuple[str, ...],
    selected_params: dict[str, dict],
    space: str,
    seed: int,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
) -> tuple[dict, list, list]:
    """Refit each model on each fold; return (predictions, fold_metrics, smote_metrics).

    predictions: {model_name: {"bank_id:period": float}}. smote_metrics: SMOTE comparison.
    """
    predictions: dict[str, dict[str, float]] = {}
    fold_metrics: list[dict[str, Any]] = []
    smote_metrics: list[dict[str, Any]] = []

    for fold_number, (train_idx, test_idx) in enumerate(folds(dataset["rows"]), 1):
        if not len(test_idx) or not len(train_idx):
            continue
        if len(np.unique(y[train_idx])) < 2 or len(np.unique(y[test_idx])) < 2:
            continue
        for name in algorithm_names:
            if time.monotonic() - wall_clock_started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            positives = int(y[train_idx].sum())
            weight = (len(train_idx) - positives) / positives if positives else 1.0
            model = model_factory(name, selected_params[name], weight, space=space)
            model.fit(dataset["X"][train_idx], y[train_idx])
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            fold_metrics.append({
                "fold": fold_number,
                "model": name,
                "pr_auc": float(average_precision_score(y[test_idx], probability)),
                "roc_auc": (float(roc_auc_score(y[test_idx], probability))
                            if len(set(y[test_idx])) > 1 else None),
                "brier": float(brier_score_loss(y[test_idx], probability)),
            })
            predictions.setdefault(name, {}).update({
                f"{dataset['rows'][i]['bank_id']}:{dataset['rows'][i]['period'].isoformat()}": float(p)
                for i, p in zip(test_idx, probability)
            })
            if sr := smote_fold_comparison(
                dataset["X"][train_idx], y[train_idx],
                dataset["X"][test_idx], y[test_idx],
                model, fold_number, name, seed,
            ):
                smote_metrics.append(sr)

    return predictions, fold_metrics, smote_metrics
