"""Generic fold-based hyperparameter search (Table 3.5).

Evaluates each configuration across all folds and returns per-config mean PR-AUC.
One call per model family.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import model_factory, _search_configs


def run_fold_search(
    dataset: dict[str, Any],
    y: np.ndarray,
    algorithm: str,
    space: str,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
) -> list[dict[str, Any]]:
    """Evaluate all configs for one algorithm across all folds (Table 3.5).

    Returns a list of {configuration, parameters, fold_pr_auc, mean_pr_auc}.
    Raises TimeoutError if wall-clock limit is exceeded.
    """
    configs = _search_configs(algorithm, space)
    config_scores: list[dict[str, Any]] = []
    for config_number, params in enumerate(configs):
        if time.monotonic() - wall_clock_started > wall_clock_hours * 3600:
            raise TimeoutError("ML search exceeded wall-clock limit")
        logger.info("configuration model=%s number=%d/%d", algorithm,
                    config_number + 1, len(configs))
        scores: list[float] = []
        for train_idx, test_idx in folds(dataset["rows"]):
            if not len(test_idx) or not len(train_idx):
                continue
            if len(np.unique(y[train_idx])) < 2 or len(np.unique(y[test_idx])) < 2:
                continue
            positives = int(y[train_idx].sum())
            weight = (len(train_idx) - positives) / positives if positives else 1.0
            candidate = model_factory(algorithm, params, weight, space=space)
            candidate.fit(dataset["X"][train_idx], y[train_idx])
            scores.append(float(average_precision_score(
                y[test_idx],
                candidate.predict_proba(dataset["X"][test_idx])[:, 1],
            )))
        config_scores.append({
            "configuration": config_number,
            "parameters": params,
            "fold_pr_auc": scores,
            "mean_pr_auc": float(np.mean(scores)),
        })
    return config_scores
