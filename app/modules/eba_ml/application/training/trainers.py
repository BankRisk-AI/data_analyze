"""Per-algorithm training functions and OOB curve for RF (Table 3.5, §3.5).

Each trainer is thin: model-specific defaults only.
Generic fold search lives in search.py.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

from app.modules.eba_ml.application.models import model_factory


def train_lr(
    dataset: dict[str, Any],
    y: np.ndarray,
    selected_params: dict[str, Any],
    space: str,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
) -> list[dict[str, Any]]:
    """Run hyperparameter search for Logistic Regression (Table 3.5).

    Returns config_scores list from run_fold_search.
    """
    from app.modules.eba_ml.application.training.search import run_fold_search
    return run_fold_search(dataset, y, "LR", space, wall_clock_started,
                           wall_clock_hours, logger)


def train_rf(
    dataset: dict[str, Any],
    y: np.ndarray,
    selected_params: dict[str, Any],
    space: str,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
) -> list[dict[str, Any]]:
    """Run hyperparameter search for Random Forest (Table 3.5).

    Returns config_scores list from run_fold_search.
    """
    from app.modules.eba_ml.application.training.search import run_fold_search
    return run_fold_search(dataset, y, "RF", space, wall_clock_started,
                           wall_clock_hours, logger)


def train_xgb(
    dataset: dict[str, Any],
    y: np.ndarray,
    selected_params: dict[str, Any],
    space: str,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
) -> list[dict[str, Any]]:
    """Run hyperparameter search for XGBoost (Table 3.5).

    Returns config_scores list from run_fold_search.
    """
    from app.modules.eba_ml.application.training.search import run_fold_search
    return run_fold_search(dataset, y, "XGB", space, wall_clock_started,
                           wall_clock_hours, logger)


TRAINERS: dict[str, Any] = {"LR": train_lr, "RF": train_rf, "XGB": train_xgb}


def oob_curve(
    dataset: dict[str, Any],
    y: np.ndarray,
    selected_params: dict[str, Any],
    final_train_idx: np.ndarray,
    space: str,
    n_estimators_candidates: tuple[int, ...] = (50, 100, 150),
) -> list[dict[str, Any]]:
    """Evaluate RF OOB score for different n_estimators candidates (§3.5).

    Used to select the final n_estimators for RF in table35 space.
    Returns list of {n_estimators, oob_score, oob_brier, oob_log_loss}.
    """
    curve = []
    for estimator_count in n_estimators_candidates:
        oob_model = model_factory(
            "RF", {**selected_params, "n_estimators": estimator_count}, space=space)
        oob_model.fit(dataset["X"][final_train_idx], y[final_train_idx])
        oob_probability = oob_model.oob_decision_function_[:, 1]
        curve.append({
            "n_estimators": estimator_count,
            "oob_score": float(oob_model.oob_score_),
            "oob_brier": float(brier_score_loss(y[final_train_idx], oob_probability)),
            "oob_log_loss": float(log_loss(
                y[final_train_idx], oob_probability, labels=(0, 1))),
        })
    return curve
